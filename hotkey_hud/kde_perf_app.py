from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from .perf_app import HudWindow as PerfHudWindow


class HudWindow(PerfHudWindow):
    """Responsive HUD with normal KDE/KWin window management."""

    def __init__(self):
        super().__init__()

        # Let KWin own decorations, snapping/tiling, maximize and restore.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
        self.setWindowState(Qt.WindowState.WindowNoState)

        # Do not carry forward a fullscreen/maximized frame geometry from the
        # older frameless implementation.
        normal_geometry = self.settings.value("normal_geometry")
        if normal_geometry is not None:
            try:
                self.setGeometry(normal_geometry)
            except Exception:
                self.resize(1160, 760)
        else:
            self.resize(1160, 760)

        hint = self.findChild(QLabel, "hint")
        if hint is not None:
            hint.setText("/ search · Ctrl+Shift+J/K navigate · Ctrl+↑↓ scroll · Ctrl+R refresh")

    def _install_shortcuts(self):
        # Never consume Alt+Arrow: those belong to KDE/KWin window movement and
        # tiling. Use non-conflicting HUD navigation shortcuts instead.
        binds = [
            ("Escape", self._escape),
            ("Ctrl+L", self.search.setFocus),
            ("Ctrl+K", self.search.setFocus),
            ("/", self.search.setFocus),
            ("Ctrl+R", self.refresh_sources),
            ("Ctrl+Shift+J", lambda: self._sidebar_move(1)),
            ("Ctrl+Shift+K", lambda: self._sidebar_move(-1)),
            ("Ctrl+Shift+L", self._sidebar_expand),
            ("Ctrl+Shift+H", self._sidebar_collapse),
            ("Ctrl+Down", lambda: self._scroll_content(1)),
            ("Ctrl+Up", lambda: self._scroll_content(-1)),
            ("Ctrl+Return", self._toggle_first_group),
            ("F11", self._toggle_fullscreen),
        ]
        for key, action in binds:
            QShortcut(QKeySequence(key), self, activated=action)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event: QCloseEvent):
        self._save_current_scroll()
        self._persist_scroll_positions()
        self._save_json("splitter_sizes", self.splitter.sizes())
        self.settings.setValue("search", self.search.text())
        self.settings.setValue(
            "normal_geometry",
            self.normalGeometry() if (self.isMaximized() or self.isFullScreen()) else self.geometry(),
        )
        self.settings.remove("geometry")
        self._executor.shutdown(wait=False, cancel_futures=True)
        QMainWindow.closeEvent(self, event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hotkey HUD")
    app.setOrganizationName("gmmpb")
    window = HudWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
