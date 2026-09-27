"""Planner window: python -m cs_planner [plan.json | exported.c]."""

import sys


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    from PyQt6 import QtWidgets as W
    from . import tooltips
    from .view import PlannerWidget

    app = W.QApplication.instance() or W.QApplication([sys.argv[0], *args])
    tooltips.install(app)
    window = W.QMainWindow()
    window.setWindowTitle("CS Planner")
    planner = PlannerWidget()
    planner.status_message.connect(window.statusBar().showMessage)
    window.setCentralWidget(planner)
    window.statusBar().showMessage("Scroll to zoom • drag to pan • click a block to inspect • right-click for plot tools")
    paths = [arg for arg in args if not arg.startswith("-")]
    if paths:
        try:
            planner.open_path(paths[0])
        except (ValueError, OSError) as error:
            W.QMessageBox.warning(window, "Cannot open configuration", str(error))
    window.resize(1440, 900)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
