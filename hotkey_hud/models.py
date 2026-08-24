from dataclasses import dataclass, field
from typing import Literal

EntryKind = Literal["shortcut", "command"]

@dataclass(slots=True)
class Entry:
    id: str
    title: str
    value: str
    description: str = ""
    kind: EntryKind = "command"
    tags: list[str] = field(default_factory=list)
    action: Literal["copy", "run"] = "copy"
    danger: bool = False

@dataclass(slots=True)
class Group:
    id: str
    title: str
    icon: str = "•"
    description: str = ""
    entries: list[Entry] = field(default_factory=list)
    children: list["Group"] = field(default_factory=list)

@dataclass(slots=True)
class Section:
    id: str
    title: str
    icon: str
    groups: list[Group] = field(default_factory=list)
