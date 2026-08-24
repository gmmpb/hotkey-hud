from __future__ import annotations

import configparser
import json
from pathlib import Path
import shlex
import shutil
import subprocess

from .models import Entry, Group


def _run(*args: str, timeout: float = 1.5) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except Exception:
        return ""


def _parse_tmux_binding(line: str) -> tuple[str, str, str, str] | None:
    """Return (table, key, command, note) for a `tmux list-keys` line."""
    try:
        tokens = shlex.split(line)
    except ValueError:
        return None

    if not tokens or tokens[0] not in {"bind-key", "bind"}:
        return None

    table = "prefix"
    note = ""
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        flag = tokens[i]
        if flag == "-T" and i + 1 < len(tokens):
            table = tokens[i + 1]
            i += 2
            continue
        if flag == "-N" and i + 1 < len(tokens):
            note = tokens[i + 1]
            i += 2
            continue
        i += 1

    if i >= len(tokens):
        return None

    key = tokens[i]
    command = " ".join(tokens[i + 1:]) or "(no command)"
    return table, key, command, note


def detect_tmux() -> Group | None:
    if not shutil.which("tmux"):
        return None

    output = _run("tmux", "list-keys", timeout=2.5)
    if not output:
        return None

    entries: list[Entry] = []
    for idx, line in enumerate(output.splitlines()):
        parsed = _parse_tmux_binding(line)
        if not parsed:
            continue
        table, key, command, note = parsed
        title = note or command
        if len(title) > 72:
            title = title[:69] + "…"
        entries.append(
            Entry(
                f"tmux-{idx}",
                title,
                f"{table} · {key}",
                line,
                "shortcut",
                ["tmux", table, key],
                source=f"tmux table: {table}",
            )
        )

    return Group(
        "tmux-live",
        f"tmux · detected ({len(entries)})",
        "▣",
        "All bindings reported by tmux list-keys",
        entries,
    ) if entries else None


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

    entries: list[Entry] = []
    for section in parser.sections():
        for action, raw in parser.items(section):
            if action.startswith("_"):
                continue
            parts = raw.split(",")
            shortcut = parts[0].strip()
            if not shortcut or shortcut == "none":
                continue
            label = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else action
            entries.append(
                Entry(
                    f"kde-{section}-{action}",
                    label,
                    shortcut,
                    f"KDE global shortcut from [{section}]",
                    "shortcut",
                    ["kde", "plasma", section, action],
                    source=section,
                )
            )

    return Group(
        "kde-live",
        f"KDE / Plasma · detected ({len(entries)})",
        "◆",
        "Shortcuts from kglobalshortcutsrc. Each card shows the component that registered it.",
        entries[:500],
    ) if entries else None


def detect_neovim() -> Group | None:
    if not shutil.which("nvim"):
        return None

    lua = r'''
lua local modes={"n","v","x","s","o","i","c","t"}; local seen={}; for _,mode in ipairs(modes) do local lists={{kind="global",maps=vim.api.nvim_get_keymap(mode)},{kind="buffer",maps=vim.api.nvim_buf_get_keymap(0,mode)}}; for _,list in ipairs(lists) do for _,m in ipairs(list.maps) do local k=mode.."\0"..m.lhs.."\0"..(m.desc or "").."\0"..(m.rhs or ""); if not seen[k] then seen[k]=true; print(vim.json.encode({mode=mode,lhs=m.lhs,desc=m.desc or "",rhs=m.rhs or "",scope=list.kind})) end end end end
'''.strip()
    output = _run("nvim", "--headless", "+" + lua, "+qa", timeout=6.0)

    mode_names = {
        "n": "Normal",
        "v": "Visual/Select",
        "x": "Visual",
        "s": "Select",
        "o": "Operator-pending",
        "i": "Insert",
        "c": "Command-line",
        "t": "Terminal",
    }

    entries: list[Entry] = []
    for idx, line in enumerate(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue

        lhs = str(m.get("lhs") or "").strip()
        mode = str(m.get("mode") or "?")
        desc = str(m.get("desc") or "").strip()
        rhs = str(m.get("rhs") or "").strip()
        scope = str(m.get("scope") or "global")
        if not lhs:
            continue

        title = desc or rhs or "Lua callback mapping"
        if len(title) > 72:
            title = title[:69] + "…"
        mode_label = mode_names.get(mode, mode)
        detail = rhs or ("Lua callback" if not desc else desc)
        entries.append(
            Entry(
                f"nvim-{idx}",
                f"[{mode_label}] {title}",
                lhs,
                detail,
                "shortcut",
                ["nvim", "neovim", mode, mode_label.lower(), scope],
                source=f"Neovim · {mode_label} · {scope}",
            )
        )

    return Group(
        "nvim-live",
        f"Neovim · detected ({len(entries)})",
        "N",
        "Loaded global and current-buffer mappings across Normal, Visual, Select, Operator, Insert, Command and Terminal modes",
        entries,
    ) if entries else None


def detect_groups() -> list[Group]:
    return [g for g in (detect_kde_global(), detect_tmux(), detect_neovim()) if g]
