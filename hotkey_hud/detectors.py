from __future__ import annotations

import configparser
from pathlib import Path
import re
import shutil
import subprocess

from .models import Entry, Group


def _run(*args: str, timeout: float = 1.5) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except Exception:
        return ""


def detect_tmux() -> Group | None:
    if not shutil.which("tmux"):
        return None
    output = _run("tmux", "list-keys")
    if not output:
        return None
    entries = []
    for idx, line in enumerate(output.splitlines()[:120]):
        m = re.match(r"bind-key(?:\s+-T\s+(\S+))?\s+(\S+)\s+(.+)", line)
        if not m:
            continue
        table, key, command = m.groups()
        entries.append(Entry(f"tmux-{idx}", command[:56], f"{table or 'prefix'} · {key}", line, "shortcut", ["tmux", key]))
    return Group("tmux-live", "tmux · detected", "▣", "Current tmux key table", entries)


def detect_kde_global() -> Group | None:
    path = Path.home() / ".config" / "kglobalshortcutsrc"
    if not path.exists():
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except Exception:
        return None
    entries = []
    for section in parser.sections():
        for action, raw in parser.items(section):
            if action.startswith("_"):
                continue
            parts = raw.split(",")
            shortcut = parts[0].strip()
            if not shortcut or shortcut == "none":
                continue
            label = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else action
            entries.append(Entry(f"kde-{section}-{action}", label, shortcut, section, "shortcut", ["kde", "plasma", section]))
    return Group("kde-live", "KDE / Plasma · detected", "◆", "Shortcuts from kglobalshortcutsrc", entries[:240]) if entries else None


def detect_neovim() -> Group | None:
    if not shutil.which("nvim"):
        return None
    script = "lua for _,m in ipairs(vim.api.nvim_get_keymap('n')) do if m.desc and m.desc ~= '' then print(m.lhs .. '\\t' .. m.desc) end end"
    output = _run("nvim", "--headless", "+" + script, "+qa", timeout=3.0)
    entries = []
    for idx, line in enumerate(output.splitlines()[:220]):
        if "\t" not in line:
            continue
        lhs, desc = line.split("\t", 1)
        entries.append(Entry(f"nvim-{idx}", desc, lhs, kind="shortcut", tags=["nvim", "neovim"]))
    return Group("nvim-live", "Neovim · detected", "N", "Described normal-mode mappings", entries) if entries else None


def detect_groups() -> list[Group]:
    return [g for g in (detect_kde_global(), detect_tmux(), detect_neovim()) if g]
