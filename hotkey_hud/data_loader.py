from __future__ import annotations

from pathlib import Path
import os
import yaml

from .models import Entry, Group, Section


def _entry(raw: dict) -> Entry:
    return Entry(
        id=str(raw.get("id") or raw["title"].lower().replace(" ", "-")),
        title=str(raw["title"]),
        value=str(raw["value"]),
        description=str(raw.get("description", "")),
        kind=str(raw.get("kind", "command")),
        tags=[str(v) for v in raw.get("tags", [])],
        action=str(raw.get("action", "copy")),
        danger=bool(raw.get("danger", False)),
    )


def _group(raw: dict) -> Group:
    return Group(
        id=str(raw["id"]),
        title=str(raw["title"]),
        icon=str(raw.get("icon", "•")),
        description=str(raw.get("description", "")),
        entries=[_entry(v) for v in raw.get("entries", [])],
        children=[_group(v) for v in raw.get("children", [])],
    )


def _read(path: Path) -> list[Section]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Section(str(s["id"]), str(s["title"]), str(s.get("icon", "•")), [_group(g) for g in s.get("groups", [])]) for s in data.get("sections", [])]


def load_sections() -> list[Section]:
    sections = _read(Path(__file__).resolve().parent / "default.yaml")
    user_file = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hotkey-hud" / "config.yaml"
    if user_file.exists():
        sections.extend(_read(user_file))
    return sections
