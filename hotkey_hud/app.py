from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .data_loader import load_sections
from .detectors import detect_groups
from .models import Entry, Group, Section


def _walk_groups(groups: list[Group]):
    for group in groups:
        yield group
        yield from _walk_groups(group.children)


def _kde_conflict_group(groups: list[Group]) -> Group | None:
    """Build a compact list of exact KDE global-shortcut collisions."""
    by_shortcut: dict[str, list[Entry]] = defaultdict(list)
    for group in _walk_groups(groups):
        for entry in group.entries:
            if entry.kind != "shortcut" or "kde" not in entry.tags:
                continue
            key = entry.value.lower().replace(" ", "")
            if key:
                by_shortcut[key].append(entry)

    conflicts: list[Entry] = []
    for entries in by_shortcut.values():
        owners = {entry.source or "unknown" for entry in entries}
        actions = {(entry.source, entry.title) for entry in entries}
        if len(actions) < 2:
            continue
        shortcut = entries[0].value
        detail = " · ".join(f"{entry.source or 'unknown'}: {entry.title}" for entry in entries)
        conflicts.append(
            Entry(
                id=f"kde-conflict-{len(conflicts)}",
                title=f"{len(entries)} actions use this shortcut",
                value=shortcut,
                description=detail,
                kind="shortcut",
                tags=["kde", "conflict", shortcut, *owners],
                source="KDE global shortcuts",
            )
        )

    if not conflicts:
        return None
    conflicts.sort(key=lambda entry: entry.value.lower())
    return Group(
        "kde-conflicts",
        f"Shortcut conflicts ({len(conflicts)})",
        "⚠",
        "Exact duplicate key combinations found in KDE global shortcuts. Some duplicates may be intentional or context-specific.",
        conflicts,
    )


class EntryCard(QFrame):
    def __init__(self, entry: Entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("entryCard")
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(12)

        text_host = QWidget()
        text_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text = QVBoxLayout(text_host)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)

        title = QLabel(entry.title)
        title.setObjectName("entryTitle")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(title)

        if entry.source:
            source = QLabel(f"Used by: {entry.source}")
            source.setObjectName("entrySource")
            source.setTextInteractionFlags(Qt.TextSelectableByMouse)
            source.setWordWrap(True)
            source.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(source)

        if entry.description:
            desc = QLabel(entry.description)
            desc.setWordWrap(True)
            desc.setObjectName("entryDescription")
            desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(desc)

        root.addWidget(text_host, 1)

        value = QLabel(entry.value)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value.setObjectName("keycap" if entry.kind == "shortcut" else "commandPill")
        value.setWordWrap(True)
        value.setMaximumWidth(330 if entry.kind == "command" else 260)
        value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        root.addWidget(value, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Shortcuts are reference material; a Copy button added noise and could
        # push long tmux/Neovim rows outside the viewport. Commands remain copyable.
        if entry.kind == "command":
            copy = QPushButton("Copy")
            copy.setObjectName("ghostButton")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(entry.value))
            root.addWidget(copy, 0, Qt.AlignmentFlag.AlignVCenter)

            if entry.action == "run" and not entry.danger:
                run = QPushButton("Run")
                run.clicked.connect(lambda: subprocess.Popen(["bash", "-lc", entry.value]))
                root.addWidget(run, 0, Qt.AlignmentFlag.AlignVCenter)


class CollapsibleGroup(QFrame):
    def __init__(self, group: Group, entries: list[Entry], expanded: bool = True, parent=None):
        super().__init__(parent)
        self.group = group
        self.setObjectName("groupPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toggle = QPushButton()
        self.toggle.setObjectName("groupToggle")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.clicked.connect(self._sync_state)
        root.addWidget(self.toggle)

        self.body = QWidget()
        self.body.setObjectName("groupBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(8)

        if group.description:
            desc = QLabel(group.description)
            desc.setWordWrap(True)
            desc.setObjectName("groupDescription")
            body_layout.addWidget(desc)

        for entry in entries:
            body_layout.addWidget(EntryCard(entry))

        root.addWidget(self.body)
        self._sync_state()

    def _sync_state(self):
        expanded = self.toggle.isChecked()
        self.body.setVisible(expanded)
        marker = "▾" if expanded else "▸"
        self.toggle.setText(f"{marker}  {self.group.icon}  {self.group.title}")

    def set_expanded(self, expanded: bool):
        self.toggle.setChecked(expanded)
        self._sync_state()


class HudWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hotkey HUD")
        self.resize(1120, 720)
        self.setMinimumSize(840, 560)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.sections = load_sections()
        detected = detect_groups()
        if detected:
            conflict_group = _kde_conflict_group(detected)
            if conflict_group:
                detected.insert(0, conflict_group)
            self.sections.insert(0, Section("detected", "Detected", "◉", detected))
        self.visible_groups: list[CollapsibleGroup] = []

        shell = QFrame()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(18, 18, 18, 14)
        outer.setSpacing(12)

        top = QHBoxLayout()
        brand = QLabel("⌨  HOTKEY HUD")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addStretch()
        hint = QLabel("Esc close  ·  / search")
        hint.setObjectName("hint")
        top.addWidget(hint)
        outer.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search shortcuts, commands, tools, descriptions…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_current)
        outer.addWidget(self.search)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        self.tree = QTreeWidget()
        self.tree.setObjectName("sidebar")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setFixedWidth(285)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setUniformRowHeights(True)
        # KDE's item-view focus indicator can render as a bright little square
        # beside the selected row. Mouse selection is enough for this launcher;
        # the background highlight remains the selection affordance.
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.itemSelectionChanged.connect(self.render_current)
        body.addWidget(self.tree)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.content)
        body.addWidget(self.scroll, 1)

        self._populate_tree()
        self._install_shortcuts()
        self._load_style()
        QTimer.singleShot(0, self.search.setFocus)

    def _populate_tree(self):
        for section in self.sections:
            parent = QTreeWidgetItem([f"{section.icon}  {section.title}"])
            parent.setData(0, Qt.UserRole, (section.id, None))
            self.tree.addTopLevelItem(parent)
            for group in section.groups:
                self._add_group(parent, section.id, group)
            parent.setExpanded(True)

        if self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first.child(0) if first.childCount() else first)

    def _add_group(self, parent, section_id: str, group: Group):
        item = QTreeWidgetItem([f"{group.icon}  {group.title}"])
        item.setData(0, Qt.UserRole, (section_id, group.id))
        parent.addChild(item)
        for child in group.children:
            self._add_group(item, section_id, child)

    def _all_groups(self, groups):
        yield from _walk_groups(groups)

    def _selected_group(self):
        items = self.tree.selectedItems()
        if not items:
            return None, None
        section_id, group_id = items[0].data(0, Qt.UserRole)
        section = next((s for s in self.sections if s.id == section_id), None)
        if not section:
            return None, None
        if group_id is None:
            return section, None
        group = next((g for g in self._all_groups(section.groups) if g.id == group_id), None)
        return section, group

    def _matches(self, entry: Entry, query: str):
        if not query:
            return True
        hay = " ".join([entry.title, entry.value, entry.description, entry.source, *entry.tags]).lower()
        return all(token in hay for token in query.lower().split())

    def _clear_content(self):
        self.visible_groups = []
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _set_all_groups(self, expanded: bool):
        for panel in self.visible_groups:
            panel.set_expanded(expanded)

    def render_current(self):
        self._clear_content()
        section, group = self._selected_group()
        query = self.search.text().strip()

        if query:
            groups = []
            for sec in self.sections:
                groups.extend(self._all_groups(sec.groups))
            title = "Search results"
        elif group:
            groups = list(self._all_groups([group]))
            title = group.title
        elif section:
            groups = list(self._all_groups(section.groups))
            title = section.title
        else:
            return

        heading = QHBoxLayout()
        page_title = QLabel(title)
        page_title.setObjectName("pageTitle")
        heading.addWidget(page_title)
        heading.addStretch()

        expand_all = QPushButton("Expand all")
        expand_all.setObjectName("ghostButton")
        expand_all.clicked.connect(lambda: self._set_all_groups(True))
        heading.addWidget(expand_all)

        collapse_all = QPushButton("Collapse all")
        collapse_all.setObjectName("ghostButton")
        collapse_all.clicked.connect(lambda: self._set_all_groups(False))
        heading.addWidget(collapse_all)
        self.content_layout.addLayout(heading)

        shown = 0
        for g in groups:
            entries = [e for e in g.entries if self._matches(e, query)]
            if not entries:
                continue
            expanded = bool(query) or (group is g) or len(entries) <= 8
            panel = CollapsibleGroup(g, entries, expanded=expanded)
            self.visible_groups.append(panel)
            self.content_layout.addWidget(panel)
            shown += len(entries)

        if shown == 0:
            empty = QLabel("No matching shortcuts or commands")
            empty.setObjectName("empty")
            self.content_layout.addWidget(empty)

        self.content_layout.addStretch(1)

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Escape"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("/"), self, activated=self.search.setFocus)

    def _load_style(self):
        path = Path(__file__).resolve().parent / "style.qss"
        self.setStyleSheet(path.read_text(encoding="utf-8"))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hotkey HUD")
    window = HudWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
