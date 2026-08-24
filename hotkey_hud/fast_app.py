from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
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
from .enhanced_detectors import detect_groups
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
        conflicts.append(
            Entry(
                f"kde-conflict-{len(conflicts)}",
                f"{len(entries)} actions use this shortcut",
                entries[0].value,
                " · ".join(f"{entry.source or 'unknown'}: {entry.title}" for entry in entries),
                "shortcut",
                ["kde", "conflict", entries[0].value],
                source="KDE global shortcuts",
            )
        )
    if not conflicts:
        return None
    return Group(
        "kde-conflicts",
        f"Shortcut conflicts ({len(conflicts)})",
        "⚠",
        "Exact duplicate KDE global shortcuts. Some can be intentional or context-specific.",
        sorted(conflicts, key=lambda e: e.value.lower()),
    )


class EntryCard(QFrame):
    def __init__(self, entry: Entry, favorite: bool, toggle_favorite, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("entryCard")
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(10)

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
            source.setWordWrap(True)
            source.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text.addWidget(source)

        if entry.description:
            desc = QLabel(entry.description)
            desc.setObjectName("entryDescription")
            desc.setWordWrap(True)
            text.addWidget(desc)

        root.addWidget(text_host, 1)

        value = QLabel(entry.value)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value.setObjectName("keycap" if entry.kind == "shortcut" else "commandPill")
        value.setWordWrap(True)
        value.setMaximumWidth(330 if entry.kind == "command" else 250)
        root.addWidget(value, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        star = QPushButton("★" if favorite else "☆")
        star.setToolTip("Remove bookmark" if favorite else "Bookmark")
        star.setFixedWidth(30)
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #8fa3ff; font-size: 17px; padding: 3px; }"
            "QPushButton:hover { background: rgba(143,163,255,0.12); border-radius: 7px; }"
        )
        star.clicked.connect(lambda: toggle_favorite(entry.id))
        root.addWidget(star, 0, Qt.AlignmentFlag.AlignVCenter)

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
    def __init__(self, group: Group, entries: list[Entry], expanded: bool, on_toggle, is_favorite, toggle_favorite, parent=None):
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
        body = QVBoxLayout(self.body)
        body.setContentsMargins(10, 8, 10, 10)
        body.setSpacing(8)
        if group.description:
            desc = QLabel(group.description)
            desc.setObjectName("groupDescription")
            desc.setWordWrap(True)
            body.addWidget(desc)
        for entry in entries:
            body.addWidget(EntryCard(entry, is_favorite(entry.id), toggle_favorite))
        root.addWidget(self.body)
        self._sync_state(False)

    def _sync_state(self, notify: bool = True):
        expanded = self.toggle.isChecked()
        self.body.setVisible(expanded)
        self.toggle.setText(f"{'▾' if expanded else '▸'}  {self.group.icon}  {self.group.title}")
        if notify:
            self.on_toggle(self.group.id, expanded)

    def set_expanded(self, expanded: bool):
        self.toggle.setChecked(expanded)
        self._sync_state()


class HudWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("gmmpb", "hotkey-hud")
        self.collapse_state = self._load_json("collapse_state", {})
        self.favorite_ids = set(self._load_json("favorites", []))
        self.scroll_positions = self._load_json("scroll_positions", {})
        self.base_sections = load_sections()
        self.detected_groups: list[Group] = []
        self.sections: list[Section] = []
        self.visible_groups: list[CollapsibleGroup] = []
        self._last_view_key: str | None = None
        self._pending_selection = (
            str(self.settings.value("selected_section", "")),
            str(self.settings.value("selected_group", "")) or None,
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hotkey-hud-detect")
        self._detect_future: Future | None = None

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
        self.status = QLabel("ready · detection loads in background")
        self.status.setObjectName("statusPill")
        top.addWidget(self.status)
        top.addStretch()
        hint = QLabel("/ search · Alt+↑↓ navigate · Ctrl+↑↓ scroll · Ctrl+R refresh")
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
        self.search.textChanged.connect(self._search_changed)
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
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.content)
        right_layout.addWidget(self.scroll, 1)

        sizes = self._load_json("splitter_sizes", [285, 850])
        if isinstance(sizes, list) and len(sizes) == 2:
            self.splitter.setSizes([int(v) for v in sizes])

        self._load_style()
        self._rebuild_sections(self._pending_selection)
        saved_search = str(self.settings.value("search", ""))
        if saved_search:
            self.search.setText(saved_search)
        self._install_shortcuts()
        QTimer.singleShot(0, self.refresh_sources)
        QTimer.singleShot(0, self.search.setFocus)

    def _load_json(self, key: str, default):
        raw = self.settings.value(key)
        if not raw:
            return default
        try:
            return json.loads(str(raw))
        except Exception:
            return default

    def _save_json(self, key: str, value):
        self.settings.setValue(key, json.dumps(value))

    def _all_entries(self):
        seen: set[str] = set()
        for section in [*self.base_sections, Section("_detected", "", "", self.detected_groups)]:
            for group in _walk_groups(section.groups):
                for entry in group.entries:
                    if entry.id not in seen:
                        seen.add(entry.id)
                        yield entry

    def _compose_sections(self) -> list[Section]:
        sections = list(self.base_sections)
        detected = list(self.detected_groups)
        if detected:
            conflict = _kde_conflict_group(detected)
            if conflict:
                detected.insert(0, conflict)
            sections.insert(0, Section("detected", "Detected", "◉", detected))

        favorites = [entry for entry in self._all_entries() if entry.id in self.favorite_ids]
        if favorites:
            sections.insert(
                0,
                Section(
                    "favorites",
                    "Favorites",
                    "★",
                    [Group("favorites-all", f"Bookmarks ({len(favorites)})", "★", "Shortcuts and commands you bookmarked.", sorted(favorites, key=lambda e: e.title.lower()))],
                ),
            )
        return sections

    def refresh_sources(self):
        if self._detect_future and not self._detect_future.done():
            return
        self._save_current_scroll()
        self.base_sections = load_sections()
        self._rebuild_sections(self._current_selection_key() or self._pending_selection)
        self.status.setText("refreshing detected shortcuts…")
        self._detect_future = self._executor.submit(detect_groups)
        QTimer.singleShot(60, self._poll_detection)

    def _poll_detection(self):
        if not self._detect_future:
            return
        if not self._detect_future.done():
            QTimer.singleShot(60, self._poll_detection)
            return
        try:
            self.detected_groups = self._detect_future.result()
            self.status.setText("live shortcuts · local config")
        except Exception as exc:
            self.detected_groups = [Group("detection-error", "Detection failed", "!", str(exc))]
            self.status.setText("detection error")
        preferred = self._pending_selection if self._pending_selection and self._pending_selection[0] else self._current_selection_key()
        self._rebuild_sections(preferred)
        self._pending_selection = ("", None)

    def _rebuild_sections(self, preferred=None):
        self.sections = self._compose_sections()
        self.tree.blockSignals(True)
        self.tree.clear()
        self._populate_tree()
        restored = self._restore_selection(preferred)
        if not restored and self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(first.child(0) if first.childCount() else first)
        self.tree.blockSignals(False)
        self.render_current()

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
        item = QTreeWidgetItem([f"{group.icon}  {title} ({count})" if count else f"{group.icon}  {title}"])
        item.setData(0, Qt.ItemDataRole.UserRole, (section_id, group.id))
        parent.addChild(item)
        for child in group.children:
            self._add_group(item, section_id, child)

    def _restore_selection(self, key) -> bool:
        if not key or not key[0]:
            return False
        for item in self._tree_items():
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                self.tree.setCurrentItem(item)
                item.setSelected(True)
                parent = item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                return True
        return False

    def _tree_items(self):
        items: list[QTreeWidgetItem] = []
        def add(item):
            items.append(item)
            for i in range(item.childCount()):
                add(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            add(self.tree.topLevelItem(i))
        return items

    def _current_selection_key(self):
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _selected_group(self):
        key = self._current_selection_key()
        if not key:
            return None, None
        section_id, group_id = key
        section = next((s for s in self.sections if s.id == section_id), None)
        if not section:
            return None, None
        if group_id is None:
            return section, None
        return section, next((g for g in _walk_groups(section.groups) if g.id == group_id), None)

    def _selection_changed(self):
        self._save_current_scroll()
        key = self._current_selection_key()
        if key:
            self.settings.setValue("selected_section", key[0])
            self.settings.setValue("selected_group", key[1] or "")
        self.render_current()

    def _search_changed(self):
        self._save_current_scroll()
        self.settings.setValue("search", self.search.text())
        self.render_current()

    def _view_key(self):
        key = self._current_selection_key() or ("", None)
        return f"{key[0]}::{key[1] or ''}::{self.search.text()}"

    def _save_current_scroll(self):
        if self._last_view_key:
            self.scroll_positions[self._last_view_key] = self.scroll.verticalScrollBar().value()

    def _restore_current_scroll(self):
        value = int(self.scroll_positions.get(self._view_key(), 0))
        self.scroll.verticalScrollBar().setValue(value)

    def _parse_query(self, query: str):
        filters: dict[str, list[str]] = defaultdict(list)
        terms: list[str] = []
        for token in query.split():
            if ":" in token:
                key, value = token.split(":", 1)
                if key.lower() in {"source", "app", "kind", "key"} and value:
                    filters[key.lower()].append(value.lower())
                    continue
            terms.append(token.lower())
        return filters, terms

    def _entry_score(self, entry: Entry, query: str) -> int | None:
        if not query:
            return 0
        filters, terms = self._parse_query(query)
        title, value, source = entry.title.lower(), entry.value.lower(), entry.source.lower()
        tags, desc = " ".join(entry.tags).lower(), entry.description.lower()
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
            if expected.replace(" ", "") not in value.replace(" ", ""):
                return None
        score = 0
        for term in terms:
            if term not in hay:
                return None
            if term.replace(" ", "") == value.replace(" ", ""):
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
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _on_group_toggle(self, group_id: str, expanded: bool):
        self.collapse_state[group_id] = expanded
        self._save_json("collapse_state", self.collapse_state)

    def _toggle_favorite(self, entry_id: str):
        self._save_current_scroll()
        if entry_id in self.favorite_ids:
            self.favorite_ids.remove(entry_id)
        else:
            self.favorite_ids.add(entry_id)
        self._save_json("favorites", sorted(self.favorite_ids))
        self._rebuild_sections(self._current_selection_key())

    def _groups_for_view(self, group: Group | None, section: Section | None, query: str):
        if query:
            return [g for sec in self.sections for g in _walk_groups(sec.groups)]
        if group:
            if group.id == "tmux-live":
                return [group, *[child for child in group.children if child.id != "tmux-advanced-tables"]]
            return list(_walk_groups([group]))
        return list(_walk_groups(section.groups)) if section else []

    def render_current(self):
        self.visible_groups = []
        self._clear_layout(self.content_layout)
        self._clear_layout(self.page_header_layout)
        section, group = self._selected_group()
        query = self.search.text().strip()
        if not section:
            return
        groups = self._groups_for_view(group, section, query)
        title = "Search results" if query else (_strip_count(group.title) if group else section.title)

        page_title = QLabel(title)
        page_title.setObjectName("pageTitle")
        self.page_header_layout.addWidget(page_title)
        self.page_header_layout.addStretch()
        for label, expanded in (("Expand all", True), ("Collapse all", False)):
            button = QPushButton(label)
            button.setObjectName("subtleButton")
            button.clicked.connect(lambda _checked=False, state=expanded: self._set_all_groups(state))
            self.page_header_layout.addWidget(button)

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
            default = bool(query) or (group is g) or len(entries) <= 8
            expanded = bool(self.collapse_state.get(g.id, default))
            panel = CollapsibleGroup(g, entries, expanded, self._on_group_toggle, lambda i: i in self.favorite_ids, self._toggle_favorite)
            self.visible_groups.append(panel)
            self.content_layout.addWidget(panel)
            shown += len(entries)

        if not shown:
            empty = QLabel("No matching shortcuts or commands. Try plain text, a key combo, or source:/app:/kind:/key: filters.")
            empty.setObjectName("empty")
            empty.setWordWrap(True)
            self.content_layout.addWidget(empty)
        self.content_layout.addStretch(1)
        self._last_view_key = self._view_key()
        QTimer.singleShot(0, self._restore_current_scroll)

    def _set_all_groups(self, expanded: bool):
        for panel in self.visible_groups:
            panel.set_expanded(expanded)

    def _sidebar_move(self, direction: int):
        current = self.tree.currentItem()
        if not current:
            return
        nxt = self.tree.itemBelow(current) if direction > 0 else self.tree.itemAbove(current)
        if nxt:
            self.tree.setCurrentItem(nxt)
            nxt.setSelected(True)

    def _sidebar_expand(self):
        item = self.tree.currentItem()
        if item:
            item.setExpanded(True)

    def _sidebar_collapse(self):
        item = self.tree.currentItem()
        if not item:
            return
        if item.isExpanded():
            item.setExpanded(False)
        elif item.parent():
            self.tree.setCurrentItem(item.parent())
            item.parent().setSelected(True)

    def _scroll_content(self, direction: int):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.value() + direction * 120)

    def _toggle_first_group(self):
        if self.visible_groups:
            panel = self.visible_groups[0]
            panel.set_expanded(not panel.toggle.isChecked())

    def _escape(self):
        if self.search.text():
            self.search.clear()
            self.search.setFocus()
        else:
            self.close()

    def _install_shortcuts(self):
        binds = [
            ("Escape", self._escape),
            ("Ctrl+L", self.search.setFocus),
            ("Ctrl+K", self.search.setFocus),
            ("/", self.search.setFocus),
            ("Ctrl+R", self.refresh_sources),
            ("Alt+Down", lambda: self._sidebar_move(1)),
            ("Alt+Up", lambda: self._sidebar_move(-1)),
            ("Alt+Right", self._sidebar_expand),
            ("Alt+Left", self._sidebar_collapse),
            ("Ctrl+Down", lambda: self._scroll_content(1)),
            ("Ctrl+Up", lambda: self._scroll_content(-1)),
            ("Ctrl+Return", self._toggle_first_group),
        ]
        for key, action in binds:
            QShortcut(QKeySequence(key), self, activated=action)

    def _load_style(self):
        path = Path(__file__).resolve().parent / "style.qss"
        self.setStyleSheet(path.read_text(encoding="utf-8"))

    def closeEvent(self, event: QCloseEvent):
        self._save_current_scroll()
        self._save_json("scroll_positions", self.scroll_positions)
        self._save_json("splitter_sizes", self.splitter.sizes())
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("search", self.search.text())
        self._executor.shutdown(wait=False, cancel_futures=True)
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
