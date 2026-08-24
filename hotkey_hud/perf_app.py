from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .fast_app import HudWindow as BaseHudWindow


class HudWindow(BaseHudWindow):
    """Performance/state fixes layered on top of the main HUD implementation."""

    def __init__(self):
        # BaseHudWindow may emit search changes while restoring the saved query,
        # so these sentinels must exist before its __init__ runs.
        self._search_timer: QTimer | None = None
        self._pending_search = False
        self._scroll_restore_target: int | None = None
        self._scroll_persist_timer: QTimer | None = None
        super().__init__()

        # Rebuilding hundreds of Qt widgets on every keypress made the line edit
        # itself feel laggy. Render only after the user pauses briefly.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(140)
        self._search_timer.timeout.connect(self._apply_search)

        # Persist scroll independently of closeEvent and retry restoration after
        # Qt has recalculated the scroll range for the freshly-rendered widgets.
        self._scroll_persist_timer = QTimer(self)
        self._scroll_persist_timer.setSingleShot(True)
        self._scroll_persist_timer.setInterval(250)
        self._scroll_persist_timer.timeout.connect(self._persist_scroll_positions)

        bar = self.scroll.verticalScrollBar()
        bar.valueChanged.connect(self._scroll_value_changed)
        bar.rangeChanged.connect(self._scroll_range_changed)

        if self._pending_search or self.search.text():
            QTimer.singleShot(0, self._apply_search)
        else:
            QTimer.singleShot(0, self._restore_current_scroll)

    def _search_changed(self, *_args):
        # During BaseHudWindow.__init__ the timer does not exist yet. Remember
        # that a render is needed, but never block text input.
        if self._search_timer is None:
            self._pending_search = True
            return
        self._search_timer.start()

    def _apply_search(self):
        self._pending_search = False
        # _last_view_key still points at the actually-rendered page, so this
        # saves its scroll before switching to the new query's page.
        self._save_current_scroll()
        self.settings.setValue("search", self.search.text())
        self.render_current()

    def _scroll_value_changed(self, value: int):
        if self._last_view_key:
            self.scroll_positions[self._last_view_key] = int(value)
            if self._scroll_persist_timer is not None:
                self._scroll_persist_timer.start()

    def _persist_scroll_positions(self):
        self._save_json("scroll_positions", self.scroll_positions)

    def _restore_current_scroll(self):
        target = int(self.scroll_positions.get(self._view_key(), 0))
        self._scroll_restore_target = target
        self._try_restore_scroll()
        # Layout/range calculation can finish over several event-loop turns,
        # especially after detected Neovim/tmux data arrives.
        QTimer.singleShot(25, self._try_restore_scroll)
        QTimer.singleShot(90, self._try_restore_scroll)
        QTimer.singleShot(180, self._try_restore_scroll)

    def _scroll_range_changed(self, _minimum: int, _maximum: int):
        if self._scroll_restore_target is not None:
            QTimer.singleShot(0, self._try_restore_scroll)

    def _try_restore_scroll(self):
        if self._scroll_restore_target is None:
            return
        bar = self.scroll.verticalScrollBar()
        target = self._scroll_restore_target
        if bar.maximum() < target:
            # Keep waiting: cards may still be entering the layout.
            return
        bar.setValue(min(target, bar.maximum()))
        if bar.value() == min(target, bar.maximum()):
            self._scroll_restore_target = None

    def closeEvent(self, event):
        self._save_current_scroll()
        self._persist_scroll_positions()
        super().closeEvent(event)


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
