"""Этап 15: строка поиска «<поле> оператор [значение]» → where для api.query_persons.

Грамматика (регистр не важен):
    query    := or_expr
    or_expr  := and_expr ( ("или" | "or" | "|") and_expr )*
    and_expr := term ( ("и" | "and" | "&") term )*
    term     := "(" query ")" | cond | text
    cond     := FIELD OP [VALUE]
    FIELD    := имя или подпись поля (person_fields), а также id | print_mark | printed_at;
                с пробелами — в кавычках или как есть (ищется самое длинное совпадение слов)
    OP       := "="  равно | "!=" не равно | "~" содержит | "^" начинается с | "пусто" | "непусто"
    VALUE    := "в кавычках" | слова до «и/или/)/конца»
    text     := слова без оператора → «содержит» в любом поле
Сравнение строковое, без учёта регистра. Ошибка → ValueError с позицией (символ, с 1).
"""
from __future__ import annotations
import re

OPS = {"=": "eq", "!=": "ne", "~": "contains", "^": "startswith", "пусто": "empty", "непусто": "not_empty"}
AND, OR = {"и", "and", "&"}, {"или", "or", "|"}
_TOK = re.compile(r'\s*(?:(?P<q>"(?:[^"\\]|\\.)*"?)|(?P<p>[()])|(?P<op>!=|=|~|\^|&|\|)|(?P<w>[^\s()"=!~^&|]+|!))')

def _tokens(text):
    out, pos = [], 0
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "": break
            raise ValueError(f"поиск: непонятный символ в позиции {pos + 1}")
        start = m.start(m.lastgroup)
        if m.group("q") is not None:
            q = m.group("q")
            if len(q) < 2 or not q.endswith('"'): raise ValueError(f"поиск: нет закрывающей кавычки (позиция {start + 1})")
            out.append(("q", q[1:-1].replace('\\"', '"'), start))
        elif m.group("p"): out.append(("p", m.group("p"), start))
        elif m.group("op"):
            v = m.group("op"); out.append(("j" if v in "&|" else "op", v, start))
        else:
            w = m.group("w"); lw = w.casefold()
            if lw in AND or lw in OR: out.append(("j", lw, start))
            elif lw in ("пусто", "непусто"): out.append(("op", lw, start))
            elif w == "!": raise ValueError(f"поиск: ожидалось «!=» в позиции {start + 1}")
            else: out.append(("w", w, start))
        pos = m.end()
    return out

def _fields(con):
    names = {"id": "id", "print_mark": "print_mark", "printed_at": "printed_at"}
    if con is not None:
        for r in con.execute("SELECT name, label FROM person_fields"):
            names[r[0].casefold()] = r[0]
            if r[1]: names.setdefault(str(r[1]).casefold(), r[0])
    return names

class _P:
    def __init__(self, toks, fields, all_fields):
        self.t, self.i, self.f, self.all = toks, 0, fields, all_fields
    def peek(self, k=0): return self.t[self.i + k] if self.i + k < len(self.t) else None
    def err(self, msg):
        tok = self.peek(); raise ValueError(f"поиск: {msg}" + (f" (позиция {tok[2] + 1})" if tok else " (конец строки)"))
    def query(self):
        parts = [self.and_()]
        while self.peek() and self.peek()[0] == "j" and self.peek()[1] in OR | {"|"}:
            self.i += 1; parts.append(self.and_())
        return parts[0] if len(parts) == 1 else {"join": "or", "terms": parts}
    def and_(self):
        parts = [self.term()]
        while self.peek() and self.peek()[0] == "j" and self.peek()[1] in AND | {"&"}:
            self.i += 1; parts.append(self.term())
        return parts[0] if len(parts) == 1 else {"join": "and", "terms": parts}
    def term(self):
        tok = self.peek()
        if tok is None: self.err("ожидалось условие")
        if tok == ("p", "(", tok[2]):
            self.i += 1; q = self.query()
            if not self.peek() or self.peek()[1] != ")": self.err("нет закрывающей скобки")
            self.i += 1; return q
        if tok[0] not in ("w", "q"): self.err(f"неожиданное «{tok[1]}»")
        # поле: кавычки или самая длинная цепочка слов, совпадающая с полем и за которой идёт оператор
        for n in range(len(self.t) - self.i, 0, -1):
            words = self.t[self.i:self.i + n]
            if any(w[0] not in ("w", "q") for w in words) or (n > 1 and any(w[0] == "q" for w in words)): continue
            nxt = self.peek(n)
            if nxt is None or nxt[0] != "op": continue
            key = " ".join(w[1] for w in words).casefold()
            if key not in self.f:
                if n == 1: raise ValueError(f"поиск: неизвестное поле «{words[0][1]}» (позиция {words[0][2] + 1})")
                continue
            self.i += n + 1; op = OPS[nxt[1]]
            if op in ("empty", "not_empty"): return {"field": self.f[key], "op": op}
            v = self.value()
            if v is None: self.err(f"после «{nxt[1]}» нужно значение")
            return {"field": self.f[key], "op": op, "value": v}
        v = self.value()
        return {"join": "or", "terms": [{"field": f, "op": "contains", "value": v} for f in self.all]} if self.all \
            else {"field": "id", "op": "contains", "value": v}
    def value(self):
        tok = self.peek()
        if tok is None: return None
        if tok[0] == "q": self.i += 1; return tok[1]
        ws = []
        while self.peek() and self.peek()[0] == "w": ws.append(self.peek()[1]); self.i += 1
        if self.peek() and self.peek()[0] == "op": self.err(f"неожиданный оператор «{self.peek()[1]}»")
        return " ".join(ws) if ws else None

def parse_search(text: str, con=None) -> dict | None:
    """Строка поиска → where для query_persons (None — пустая строка). con нужен для имён/подписей полей
    (без con известны только id/print_mark/printed_at). Ошибка → ValueError с позицией."""
    toks = _tokens(str(text or ""))
    if not toks: return None
    all_fields = [r[0] for r in con.execute("SELECT name FROM person_fields ORDER BY sort_order, name")] if con is not None else []
    p = _P(toks, _fields(con), all_fields)
    w = p.query()
    if p.peek() is not None: p.err(f"лишнее «{p.peek()[1]}»")
    return w

def search_persons(con, text: str, **query_kw) -> list[dict]:
    """query_persons(con, parse_search(text, con), **query_kw); пустая строка — все записи (с фильтрами query_kw)."""
    from ..api import query_persons
    return query_persons(con, parse_search(text, con), **query_kw)
