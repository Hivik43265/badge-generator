import sys
from PyQt6.QtWidgets import QApplication


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--self-test" in argv:
        from ui.self_test import run
        return run(argv)
    app = QApplication(argv); app.setApplicationName("BadgeGenerator")
    from ui import errors
    errors.install()
    from ui.main_window import MainWindow
    w = MainWindow(); w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
