from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .kde_perf_app import HudWindow as KdeHudWindow
from .models import Entry, Group


def _cache_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "hotkey-hud" / "detected.json"


def _entry_to_dict(entry: Entry) -> dict:
    return {
        "id": entry.id,
        "title": entry.title,
        "value": entry.value,
        "description": entry.description,
        "kind": entry.kind,
        "tags": entry.tags,
        "action": entry.action,
        "danger": entry.danger,
        "source": entry.source,
    }


def _entry_from_dict(raw: dict) -> Entry:
    return Entry(
        id=str(raw["id"]),
        title=str(raw["title"]),
        value=str(raw["value"]),
        description=str(raw.get("description", "")),
        kind=str(raw.get("kind", "command")),
        tags=[str(value) for value in raw.get("tags", [])],
        action=str(raw.get("action", "copy")),
        danger=bool(raw.get("danger", False)),
        source=str(raw.get("source", "")),
    )


def _group_to_dict(group: Group) -> dict:
    return {
        "id": group.id,
        "title": group.title,
        "icon": group.icon,
        "description": group.description,
        "entries": [_entry_to_dict(entry) for entry in group.entries],
        "children": [_group_to_dict(child) for child in group.children],
    }


def _group_from_dict(raw: dict) -> Group:
    return Group(
        id=str(raw["id"]),
        title=str(raw["title"]),
        icon=str(raw.get("icon", "•")),
        description=str(raw.get("description", "")),
        entries=[_entry_from_dict(entry) for entry in raw.get("entries", [])],
        children=[_group_from_dict(child) for child in raw.get("children", [])],
    )


def _serialize(groups: list[Group]) -> str:
    return json.dumps([_group_to_dict(group) for group in groups], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_cached_groups() -> tuple[list[Group], str]:
    path = _cache_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
        groups = [_group_from_dict(group) for group in raw]
        return groups, _serialize(groups)
    except Exception:
        return [], ""


def _save_cached_groups(groups: list[Group]) -> str:
    serialized = _serialize(groups)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(serialized, encoding="utf-8")
    tmp.replace(path)
    return serialized


class HudWindow(KdeHudWindow):
    """KDE HUD with persistent detection cache and non-blocking search typing."""

    def __init__(self):
        cached_groups, cached_serialized = _load_cached_groups()
        self._cached_serialized = cached_serialized
        super().__init__()

        # The base window intentionally starts without detected data so first
        # paint is immediate. On subsequent launches, hydrate from disk before
        # the event loop starts; the background scan then only refreshes it.
        if cached_groups:
            self.detected_groups = cached_groups
            preferred = self._current_selection_key() or self._pending_selection
            self._rebuild_sections(preferred)
            self.status.setText("cached shortcuts · refreshing in background")

        # 140 ms was short enough that normal typing repeatedly hit expensive Qt
        # card reconstruction. Wait until the user has actually paused typing.
        if self._search_timer is not None:
            self._search_timer.setInterval(420)

    def _poll_detection(self):
        if not self._detect_future:
            return
        if not self._detect_future.done():
            QTimer.singleShot(75, self._poll_detection)
            return

        try:
            fresh_groups = self._detect_future.result()
            fresh_serialized = _serialize(fresh_groups)
            changed = fresh_serialized != self._cached_serialized
            self.detected_groups = fresh_groups
            if changed:
                self._cached_serialized = _save_cached_groups(fresh_groups)
                preferred = (
                    self._pending_selection
                    if self._pending_selection and self._pending_selection[0]
                    else self._current_selection_key()
                )
                self._save_current_scroll()
                self._rebuild_sections(preferred)
            self.status.setText("live shortcuts · cache up to date")
        except Exception as exc:
            # Keep a valid cache visible if refresh fails. A transient detector
            # error should not make a previously-working launch worse.
            if self.detected_groups:
                self.status.setText(f"cached shortcuts · refresh failed: {type(exc).__name__}")
            else:
                self.status.setText(f"detection failed: {type(exc).__name__}")
        finally:
            self._pending_selection = ("", None)


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
