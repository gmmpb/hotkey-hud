from __future__ import annotations

from .detectors import (
    _find_executable,
    _parse_tmux_binding,
    _run,
    _slug,
    detect_kde_global,
    detect_neovim as _detect_neovim,
    detect_zsh_aliases,
)
from .models import Entry, Group


PRIMARY_TMUX_TABLES = ("prefix", "root", "copy-mode-vi", "copy-mode")


def detect_tmux() -> Group | None:
    tmux = _find_executable("tmux")
    if not tmux:
        return None
    output = _run(tmux, "list-keys", timeout=2.5)
    if not output:
        return None

    by_table: dict[str, list[Entry]] = {}
    for idx, line in enumerate(output.splitlines()):
        parsed = _parse_tmux_binding(line)
        if not parsed:
            continue
        table, key, command, note = parsed
        title = note or command
        if len(title) > 72:
            title = title[:69] + "…"
        by_table.setdefault(table, []).append(
            Entry(
                f"tmux-{idx}",
                title,
                f"{table} · {key}",
                line,
                "shortcut",
                ["tmux", table, key],
                source=f"tmux · {table}",
            )
        )

    primary: list[Group] = []
    advanced: list[Group] = []
    for table, entries in sorted(by_table.items(), key=lambda item: (PRIMARY_TMUX_TABLES.index(item[0]) if item[0] in PRIMARY_TMUX_TABLES else 99, item[0])):
        group = Group(
            f"tmux-table-{_slug(table)}",
            f"{table} ({len(entries)})",
            "·",
            f"Bindings in tmux key table '{table}'",
            sorted(entries, key=lambda e: e.value.lower()),
        )
        (primary if table in PRIMARY_TMUX_TABLES else advanced).append(group)

    if advanced:
        primary.append(
            Group(
                "tmux-advanced-tables",
                f"Advanced / internal tables ({sum(len(g.entries) for g in advanced)})",
                "…",
                "Less commonly useful tmux key tables, kept out of the main list.",
                children=advanced,
            )
        )

    total = sum(len(g.entries) for g in primary if g.id != "tmux-advanced-tables") + sum(len(g.entries) for g in advanced)
    return Group(
        "tmux-live",
        f"tmux · detected ({total})",
        "▣",
        "Common tmux tables first; internal tables are tucked under Advanced.",
        children=primary,
    ) if total else None


def _nvim_essentials() -> Group:
    def s(i: str, title: str, key: str, desc: str, tags: list[str] | None = None) -> Entry:
        return Entry(
            f"nvim-essential-{i}",
            title,
            key,
            desc,
            "shortcut",
            ["nvim", "neovim", "essential", *(tags or [])],
            source="Vim / Neovim essentials",
        )

    entries = [
        s("visual-char", "Select characters", "v", "Enter character-wise Visual mode.", ["select", "visual"]),
        s("visual-line", "Select whole lines", "V", "Enter line-wise Visual mode.", ["select", "visual"]),
        s("visual-block", "Block / column selection", "Ctrl+V", "Enter Visual Block mode.", ["select", "visual", "column"]),
        s("select-all", "Select entire file", "ggVG", "Jump to the top, start line selection, then extend to the end.", ["select", "all"]),
        s("reselect", "Reselect last selection", "gv", "Restore the previous Visual selection.", ["select", "visual"]),
        s("line-end", "End of line", "$", "Move to the end of the current line.", ["motion", "line"]),
        s("line-start", "Start / first text on line", "0  /  ^", "0 goes to column 1; ^ goes to the first non-blank character.", ["motion", "line"]),
        s("char", "Previous / next character", "h  /  l", "Move one character left or right.", ["motion"]),
        s("word", "Next / previous word", "w  /  b", "Move by words; e moves to the end of a word.", ["motion", "word"]),
        s("paragraph", "Previous / next paragraph", "{  /  }", "Jump between paragraph/block boundaries.", ["motion", "paragraph"]),
        s("half-page", "Half-page down / up", "Ctrl+D  /  Ctrl+U", "Fast vertical navigation while keeping context.", ["motion", "scroll"]),
        s("file-ends", "Top / bottom of file", "gg  /  G", "Jump to the first or last line.", ["motion"]),
        s("match-bracket", "Matching bracket", "%", "Jump between matching (), [], {}, or other matched pairs.", ["motion", "bracket"]),
        s("word-search", "Highlight word under cursor", "*  /  #", "Search forward/backward for the word under the cursor; n/N moves between matches.", ["search", "highlight"]),
        s("search-next", "Next / previous search result", "n  /  N", "Repeat the last search forward or backward.", ["search"]),
        s("comment-line", "Toggle comment on line", "gcc", "Common LazyVim/comment.nvim style mapping for the current line.", ["comment", "lazyvim"]),
        s("comment-selection", "Toggle comment on selection", "Visual: gc", "Select text, then use gc with the common LazyVim/comment operator mapping.", ["comment", "visual", "lazyvim"]),
        s("indent-selection", "Indent / outdent selection", "Visual: >  /  <", "Indent or outdent selected lines; gv reselects afterward if needed.", ["visual", "indent"]),
        s("inner-word", "Select inner / around word", "viw  /  vaw", "Select a word without or with surrounding whitespace.", ["select", "text-object"]),
        s("change-word", "Change inner word", "ciw", "Replace the word under the cursor without manually selecting it.", ["edit", "text-object"]),
        s("delete-word", "Delete inner word", "diw", "Delete the word under the cursor.", ["edit", "text-object"]),
        s("repeat", "Repeat last change", ".", "Repeat the most recent editing change.", ["edit", "repeat"]),
        s("jump-list", "Jump back / forward", "Ctrl+O  /  Ctrl+I", "Navigate the jump list, useful after definitions/searches.", ["motion", "jump"]),
        s("definition", "Go to definition", "gd", "Common LSP mapping in Neovim/LazyVim.", ["lsp", "dev"]),
        s("references", "Find references", "gr", "Common LSP mapping; exact behavior can vary by config.", ["lsp", "dev"]),
        s("hover", "Show symbol documentation", "K", "Common LSP hover/documentation mapping.", ["lsp", "dev"]),
    ]
    return Group(
        "nvim-essentials",
        f"Essentials I forget ({len(entries)})",
        "★",
        "A compact everyday Vim/Neovim developer guide. Plugin-specific mappings are labelled as such.",
        entries,
    )


def detect_neovim() -> Group:
    group = _detect_neovim()
    if group.id == "nvim-live" and "detected" in group.title.lower():
        group.children.insert(0, _nvim_essentials())
    else:
        # Even if runtime detection fails, the useful built-in guide remains available.
        group.children.insert(0, _nvim_essentials())
    return group


def detect_groups() -> list[Group]:
    return [g for g in (detect_kde_global(), detect_tmux(), detect_neovim(), detect_zsh_aliases()) if g]
