from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from .fast_app import HudWindow as BaseHudWindow


class HudWindow(BaseHudWindow):
    """KDE-friendly HUD window.

    Keep KWin in charge of moving, tiling, maximizing and restoring the window.
    The previous frameless window plus Alt+Arrow application shortcuts competed
    with compositor shortcuts and made maximize/restore behavior unreliable.
    """

    def __init__(self):
        super().__init__()

        # Use a normal managed window. The content itself keeps the HUD styling,
        # but KWin now owns decorations, tiling, maximize/restore and movement.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
        self.setWindowState(Qt.WindowState.WindowNoState)

        # Do not reuse a previously saved maximized/fullscreen frame geometry.
        # From this version onward we persist only the normal window rectangle.
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
        # Deliberately do not consume Alt+Arrow. Those combinations belong to
        # KDE/KWin so users can move/tile the HUD like every other window.
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
        # Persist the normal rectangle, never a maximized/fullscreen frame. This
        # prevents reopening into an un-restorable giant window.
        self._save_current_scroll()
        self._save_json("scroll_positions", self.scroll_positions)
        self._save_json("splitter_sizes", self.splitter.sizes())
        self.settings.setValue("search", self.search.text())
        self.settings.setValue("normal_geometry", self.normalGeometry() if (self.isMaximized() or self.isFullScreen()) else self.geometry())
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
