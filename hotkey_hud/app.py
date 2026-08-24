from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon, QKeySequence, QShortcut
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
    QSplitter,
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


def _group_count(group: Group) -> int:
    return len(group.entries) + sum(_group_count(child) for child in group.children)


def _strip_count(title: str) -> str:
    return re.sub(r"\s+\(\d+\)$", "", title)


def _kde_conflict_group(groups: list[Group]) -> Group | None:
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
                tags=["kde", "conflict", shortcut],
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
        value.setMaximumWidth(330 if entry.kind == "command" else 250)
        value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        root.addWidget(value, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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
    def __init__(self, group: Group, entries: list[Entry], expanded: bool, on_toggle, parent=None):
        super().__init__(parent)
        self.group = group
        self.on_toggle = on_toggle
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
        self._sync_state(notify=False)

    def _sync_state(self, notify: bool = True):
        expanded = self.toggle.isChecked()
        self.body.setVisible(expanded)
        marker = "▾" if expanded else "▸"
        self.toggle.setText(f"{marker}  {self.group.icon}  {self.group.title}")
        if notify:
            self.on_toggle(self.group.id, expanded)

    def set_expanded(self, expanded: bool):
        self.toggle.setChecked(expanded)
        self._sync_state()


class HudWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("gmmpb", "hotkey-hud")
        self.collapse_state = self._load_json_setting("collapse_state", {})
        self.visible_groups: list[CollapsibleGroup] = []
        self.sections: list[Section] = []

        self.setWindowTitle("Hotkey HUD")
        self.setWindowIcon(QIcon.fromTheme("input-keyboard"))
        self.resize(1160, 760)
        self.setMinimumSize(860, 560)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

        shell = QFrame()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)

        top = QHBoxLayout()
        icon = QLabel()
        pixmap = self.windowIcon().pixmap(22, 22)
        if not pixmap.isNull():
            icon.setPixmap(pixmap)
            top.addWidget(icon)
        brand = QLabel("HOTKEY HUD")
        brand.setObjectName("brand")
        top.addWidget(brand)
        source_status = QLabel("live shortcuts · local config")
        source_status.setObjectName("statusPill")
        top.addWidget(source_status)
        top.addStretch()
        hint = QLabel("Esc close  ·  / search  ·  Ctrl+R refresh")
        hint.setObjectName("hint")
        top.addWidget(hint)
        refresh = QPushButton("↻  Refresh")
        refresh.setObjectName("ghostButton")
        refresh.clicked.connect(self.refresh_sources)
        top.addWidget(refresh)
        outer.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…  source:kwin  app:nvim  kind:shortcut  key:meta+f")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_current)
        outer.addWidget(self.search)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setChildrenCollapsible(False)
        outer.addWidget(self.splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setObjectName("sidebar")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(15)
        self.tree.setMinimumWidth(220)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setUniformRowHeights(True)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.splitter.addWidget(self.tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        self.page_header = QWidget()
        self.page_header.setObjectName("pageHeader")
        self.page_header_layout = QHBoxLayout(self.page_header)
        self.page_header_layout.setContentsMargins(2, 0, 2, 0)
        right_layout.addWidget(self.page_header)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.content)
        right_layout.addWidget(self.scroll, 1)

        splitter_sizes = self._load_json_setting("splitter_sizes", [285, 850])
        if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2:
            self.splitter.setSizes([int(v) for v in splitter_sizes])

        self._load_style()
        self._reload_sections(restore_selection=True)
        self._install_shortcuts()
        QTimer.singleShot(0, self.search.setFocus)

    def _load_json_setting(self, key: str, default):
        raw = self.settings.value(key)
        if not raw:
            return default
        try:
            return json.loads(str(raw))
        except Exception:
            return default

    def _save_json_setting(self, key: str, value):
        self.settings.setValue(key, json.dumps(value))

    def _build_sections(self):
        sections = load_sections()
        detected = detect_groups()
        if detected:
            conflict_group = _kde_conflict_group(detected)
            if conflict_group:
                detected.insert(0, conflict_group)
            sections.insert(0, Section("detected", "Detected", "◉", detected))
        return sections

    def _reload_sections(self, restore_selection: bool = False):
        current = self._current_selection_key() if self.tree.topLevelItemCount() else None
        if restore_selection:
            current = (
                str(self.settings.value("selected_section", "")),
                str(self.settings.value("selected_group", "")) or None,
            )

        self.sections = self._build_sections()
        self.tree.blockSignals(True)
        self.tree.clear()
        self._populate_tree()
        self.tree.blockSignals(False)

        if not self._restore_selection(current):
            if self.tree.topLevelItemCount():
                first = self.tree.topLevelItem(0)
                self.tree.setCurrentItem(first.child(0) if first.childCount() else first)
        self.render_current()

    def refresh_sources(self):
        self._reload_sections()

    def _populate_tree(self):
        for section in self.sections:
            parent = QTreeWidgetItem([f"{section.icon}  {section.title}"])
            parent.setData(0, Qt.ItemDataRole.UserRole, (section.id, None))
            self.tree.addTopLevelItem(parent)
            for group in section.groups:
                self._add_group(parent, section.id, group)
            parent.setExpanded(True)

    def _add_group(self, parent, section_id: str, group: Group):
        count = _group_count(group)
        title = _strip_count(group.title)
        display = f"{group.icon}  {title} ({count})" if count else f"{group.icon}  {title}"
        item = QTreeWidgetItem([display])
        item.setData(0, Qt.ItemDataRole.UserRole, (section_id, group.id))
        parent.addChild(item)
        for child in group.children:
            self._add_group(item, section_id, child)

    def _all_groups(self, groups):
        yield from _walk_groups(groups)

    def _current_selection_key(self):
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _restore_selection(self, key) -> bool:
        if not key or not key[0]:
            return False
        iterator = QTreeWidgetItemIteratorCompat(self.tree)
        for item in iterator:
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                self.tree.setCurrentItem(item)
                item.setSelected(True)
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                return True
        return False

    def _selection_changed(self):
        key = self._current_selection_key()
        if key:
            self.settings.setValue("selected_section", key[0])
            self.settings.setValue("selected_group", key[1] or "")
        self.render_current()

    def _selected_group(self):
        items = self.tree.selectedItems()
        if not items:
            return None, None
        section_id, group_id = items[0].data(0, Qt.ItemDataRole.UserRole)
        section = next((s for s in self.sections if s.id == section_id), None)
        if not section:
            return None, None
        if group_id is None:
            return section, None
        group = next((g for g in self._all_groups(section.groups) if g.id == group_id), None)
        return section, group

    def _parse_query(self, query: str):
        filters: dict[str, list[str]] = defaultdict(list)
        terms: list[str] = []
        for token in query.split():
            if ":" in token:
                key, value = token.split(":", 1)
                key = key.lower()
                if key in {"source", "app", "kind", "key"} and value:
                    filters[key].append(value.lower())
                    continue
            terms.append(token.lower())
        return filters, terms

    def _entry_score(self, entry: Entry, query: str) -> int | None:
        if not query:
            return 0
        filters, terms = self._parse_query(query)
        title = entry.title.lower()
        value = entry.value.lower()
        source = entry.source.lower()
        tags = " ".join(entry.tags).lower()
        desc = entry.description.lower()
        hay = " ".join((title, value, source, tags, desc))

        for expected in filters.get("source", []):
            if expected not in source:
                return None
        for expected in filters.get("app", []):
            if expected not in source and expected not in tags:
                return None
        for expected in filters.get("kind", []):
            if expected != entry.kind.lower():
                return None
        for expected in filters.get("key", []):
            compact_expected = expected.replace(" ", "")
            compact_value = value.replace(" ", "")
            if compact_expected not in compact_value:
                return None

        score = 0
        for term in terms:
            if term not in hay:
                return None
            compact_term = term.replace(" ", "")
            if compact_term == value.replace(" ", ""):
                score += 140
            elif title == term:
                score += 120
            elif title.startswith(term):
                score += 90
            elif term in title:
                score += 70
            elif term in value:
                score += 60
            elif term in source:
                score += 35
            elif term in tags:
                score += 25
            else:
                score += 10
        return score

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)
                child_layout.deleteLater()

    def _clear_content(self):
        self.visible_groups = []
        self._clear_layout(self.content_layout)
        self._clear_layout(self.page_header_layout)

    def _on_group_toggle(self, group_id: str, expanded: bool):
        self.collapse_state[group_id] = expanded
        self._save_json_setting("collapse_state", self.collapse_state)

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
            title = _strip_count(group.title)
        elif section:
            groups = list(self._all_groups(section.groups))
            title = section.title
        else:
            return

        page_title = QLabel(title)
        page_title.setObjectName("pageTitle")
        self.page_header_layout.addWidget(page_title)
        self.page_header_layout.addStretch()

        expand_all = QPushButton("Expand all")
        expand_all.setObjectName("subtleButton")
        expand_all.clicked.connect(lambda: self._set_all_groups(True))
        self.page_header_layout.addWidget(expand_all)

        collapse_all = QPushButton("Collapse all")
        collapse_all.setObjectName("subtleButton")
        collapse_all.clicked.connect(lambda: self._set_all_groups(False))
        self.page_header_layout.addWidget(collapse_all)

        shown = 0
        for g in groups:
            ranked: list[tuple[int, Entry]] = []
            for entry in g.entries:
                score = self._entry_score(entry, query)
                if score is not None:
                    ranked.append((score, entry))
            if not ranked:
                continue
            ranked.sort(key=lambda pair: (-pair[0], pair[1].title.lower()))
            entries = [entry for _, entry in ranked]

            default_expanded = bool(query) or (group is g) or len(entries) <= 8
            expanded = bool(self.collapse_state.get(g.id, default_expanded))
            panel = CollapsibleGroup(g, entries, expanded=expanded, on_toggle=self._on_group_toggle)
            self.visible_groups.append(panel)
            self.content_layout.addWidget(panel)
            shown += len(entries)

        if shown == 0:
            empty = QLabel(
                "No matching shortcuts or commands.\n"
                "Try plain text, a key combo, or filters such as source:kwin, app:nvim, kind:shortcut, key:meta+f."
            )
            empty.setWordWrap(True)
            empty.setObjectName("empty")
            self.content_layout.addWidget(empty)

        self.content_layout.addStretch(1)

    def _escape(self):
        if self.search.text():
            self.search.clear()
            self.search.setFocus()
        else:
            self.close()

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("/"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.refresh_sources)

    def _load_style(self):
        path = Path(__file__).resolve().parent / "style.qss"
        self.setStyleSheet(path.read_text(encoding="utf-8"))

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue("geometry", self.saveGeometry())
        self._save_json_setting("splitter_sizes", self.splitter.sizes())
        super().closeEvent(event)


class QTreeWidgetItemIteratorCompat:
    """Tiny iterator helper that avoids depending on a separate Qt iterator import."""

    def __init__(self, tree: QTreeWidget):
        self.items: list[QTreeWidgetItem] = []
        for i in range(tree.topLevelItemCount()):
            self._append(tree.topLevelItem(i))

    def _append(self, item: QTreeWidgetItem):
        self.items.append(item)
        for i in range(item.childCount()):
            self._append(item.child(i))

    def __iter__(self):
        return iter(self.items)


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
