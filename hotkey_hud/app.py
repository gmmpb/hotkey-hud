from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .data_loader import load_sections
from .detectors import detect_groups
from .models import Entry, Group, Section


class EntryCard(QFrame):
    def __init__(self, entry: Entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("entryCard")
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 11, 14, 11)
        root.setSpacing(12)
        text = QVBoxLayout()
        title = QLabel(entry.title)
        title.setObjectName("entryTitle")
        text.addWidget(title)
        if entry.description:
            desc = QLabel(entry.description)
            desc.setWordWrap(True)
            desc.setObjectName("entryDescription")
            text.addWidget(desc)
        root.addLayout(text, 1)
        value = QLabel(entry.value)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value.setObjectName("keycap" if entry.kind == "shortcut" else "commandPill")
        value.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        root.addWidget(value)
        copy = QPushButton("Copy")
        copy.setObjectName("ghostButton")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(entry.value))
        root.addWidget(copy)
        if entry.action == "run" and not entry.danger:
            run = QPushButton("Run")
            run.clicked.connect(lambda: subprocess.Popen(["bash", "-lc", entry.value]))
            root.addWidget(run)


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
            self.sections.insert(0, Section("detected", "Detected", "◉", detected))

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
        self.tree.setFixedWidth(250)
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
            if first.childCount():
                self.tree.setCurrentItem(first.child(0))
            else:
                self.tree.setCurrentItem(first)

    def _add_group(self, parent, section_id: str, group: Group):
        item = QTreeWidgetItem([f"{group.icon}  {group.title}"])
        item.setData(0, Qt.UserRole, (section_id, group.id))
        parent.addChild(item)
        for child in group.children:
            self._add_group(item, section_id, child)

    def _all_groups(self, groups):
        for group in groups:
            yield group
            yield from self._all_groups(group.children)

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
        hay = " ".join([entry.title, entry.value, entry.description, *entry.tags]).lower()
        return all(token in hay for token in query.lower().split())

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

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
            groups = [group]
            title = group.title
        elif section:
            groups = list(self._all_groups(section.groups))
            title = section.title
        else:
            return
        page_title = QLabel(title)
        page_title.setObjectName("pageTitle")
        self.content_layout.addWidget(page_title)
        shown = 0
        for g in groups:
            entries = [e for e in g.entries if self._matches(e, query)]
            if not entries:
                continue
            header = QLabel(f"{g.icon}  {g.title}")
            header.setObjectName("groupTitle")
            self.content_layout.addWidget(header)
            if g.description:
                d = QLabel(g.description)
                d.setObjectName("groupDescription")
                self.content_layout.addWidget(d)
            for entry in entries:
                self.content_layout.addWidget(EntryCard(entry))
                shown += 1
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
