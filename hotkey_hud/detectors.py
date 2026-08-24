from __future__ import annotations

import configparser
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

from .models import Entry, Group


def _run_result(*args: str, timeout: float = 1.5) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception:
        return None


def _run(*args: str, timeout: float = 1.5) -> str:
    result = _run_result(*args, timeout=timeout)
    return result.stdout if result else ""


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "other"


def _find_executable(name: str) -> str | None:
    """Find tools even when the GUI desktop environment has a reduced PATH."""
    found = shutil.which(name)
    if found:
        return found

    for candidate in (
        Path.home() / ".local" / "bin" / name,
        Path.home() / ".cargo" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/usr/bin") / name,
        Path("/snap/bin") / name,
    ):
        if candidate.is_file():
            return str(candidate)

    shell = shutil.which("zsh") or shutil.which("bash")
    if shell:
        result = _run_result(shell, "-lc", f"command -v {shlex.quote(name)}", timeout=2.5)
        if result and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[-1]
    return None


def _parse_tmux_binding(line: str) -> tuple[str, str, str, str] | None:
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
    tmux = _find_executable("tmux")
    if not tmux:
        return None
    output = _run(tmux, "list-keys", timeout=2.5)
    if not output:
        return None
    by_table: dict[str, list[Entry]] = {}
    total = 0
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
        total += 1
    if not total:
        return None
    preferred = {"prefix": 0, "root": 1, "copy-mode-vi": 2, "copy-mode": 3}
    children = [
        Group(
            f"tmux-table-{_slug(table)}",
            f"{table} ({len(entries)})",
            "·",
            f"Bindings in tmux key table '{table}'",
            sorted(entries, key=lambda e: e.value.lower()),
        )
        for table, entries in sorted(by_table.items(), key=lambda item: (preferred.get(item[0], 99), item[0]))
    ]
    return Group(
        "tmux-live",
        f"tmux · detected ({total})",
        "▣",
        "Bindings reported by tmux list-keys, grouped by key table",
        children=children,
    )


def _kde_category(section: str, action: str, label: str) -> tuple[str, str, str]:
    text = f"{section} {action} {label}".lower()
    section_l = section.lower()
    if any(word in section_l for word in ("wacom", "tablet", "touch", "input")) or any(
        word in text for word in ("stylus", "tablet", "touch tool")
    ):
        return "input", "Input devices", "⌨"
    if "spectacle" in section_l or any(word in text for word in ("screenshot", "screen shot", "capture")):
        return "screenshots", "Screenshots & capture", "▣"
    if any(word in text for word in ("volume", "audio", "media", "play", "pause", "microphone", "mute", "next track", "previous track")):
        return "media", "Media & audio", "♪"
    if any(word in text for word in ("window", "maximize", "minimize", "fullscreen", "tile", "raise", "lower", "close window")):
        return "windows", "Window management", "□"
    if any(word in text for word in ("desktop", "workspace", "activity", "overview", "present windows", "screen", "monitor", "output")):
        return "workspace", "Desktops & screens", "▦"
    if any(word in text for word in ("krunner", "launcher", "launch ", "open ", "application")):
        return "launchers", "Launchers & applications", "⌘"
    if any(word in text for word in ("logout", "log out", "lock screen", "suspend", "hibernate", "power off", "shutdown", "reboot")):
        return "session", "Session & system", "⏻"
    return "other", "Other", "…"


def _pretty_kde_owner(section: str) -> str:
    known = {
        "kwin": "KWin",
        "plasmashell": "Plasma Shell",
        "wacomtablet": "Wacom Tablet",
        "org.kde.spectacle.desktop": "Spectacle",
        "org.kde.konsole.desktop": "Konsole",
        "org.kde.dolphin.desktop": "Dolphin",
        "kded5": "KDE Daemon",
        "kded6": "KDE Daemon",
    }
    if section in known:
        return known[section]
    value = section
    for prefix in ("org.kde.", "services]["):
        value = value.replace(prefix, "")
    value = value.removesuffix(".desktop")
    return value.replace("-", " ").replace("_", " ").title() or section


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

    categories: dict[str, tuple[str, str, dict[str, list[Entry]]]] = {}
    total = 0
    for section in parser.sections():
        for action, raw in parser.items(section):
            if action.startswith("_"):
                continue
            parts = raw.split(",")
            shortcut = parts[0].strip()
            if not shortcut or shortcut.lower() == "none":
                continue
            label = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else action
            category_id, category_title, category_icon = _kde_category(section, action, label)
            if category_id not in categories:
                categories[category_id] = (category_title, category_icon, {})
            owners = categories[category_id][2]
            pretty_owner = _pretty_kde_owner(section)
            owners.setdefault(section, []).append(
                Entry(
                    f"kde-{section}-{action}",
                    label,
                    shortcut,
                    f"KDE global shortcut · component id: {section}",
                    "shortcut",
                    ["kde", "plasma", section, pretty_owner, action, category_title],
                    source=pretty_owner,
                )
            )
            total += 1

    if not total:
        return None

    order = ["windows", "workspace", "screenshots", "media", "input", "launchers", "session", "other"]
    category_groups: list[Group] = []
    for category_id in order:
        if category_id not in categories:
            continue
        title, icon, owners = categories[category_id]
        owner_groups = []
        for owner, entries in sorted(owners.items(), key=lambda item: _pretty_kde_owner(item[0]).lower()):
            pretty = _pretty_kde_owner(owner)
            owner_groups.append(
                Group(
                    f"kde-{category_id}-{_slug(owner)}",
                    f"{pretty} ({len(entries)})",
                    "·",
                    f"KDE component: {owner}",
                    sorted(entries, key=lambda e: e.title.lower()),
                )
            )
        count = sum(len(entries) for entries in owners.values())
        category_groups.append(
            Group(
                f"kde-category-{category_id}",
                f"{title} ({count})",
                icon,
                f"Detected KDE shortcuts related to {title.lower()}",
                children=owner_groups,
            )
        )
    return Group(
        "kde-live",
        f"KDE / Plasma · detected ({total})",
        "◆",
        "Shortcuts from kglobalshortcutsrc, organized by purpose and owning component",
        children=category_groups,
    )


def _nvim_failure(detail: str, nvim_path: str | None = None) -> Group:
    detail = detail.strip() or "Neovim did not produce mapping data."
    if len(detail) > 900:
        detail = detail[-900:]
    path_note = f"Executable: {nvim_path}" if nvim_path else "Neovim executable was not found in the HUD environment."
    return Group(
        "nvim-live",
        "Neovim · detection failed",
        "N",
        f"{path_note}\n{detail}",
        [
            Entry(
                "nvim-diagnostic",
                "Neovim detector diagnostic",
                "command -v nvim && nvim --headless '+verbose map' '+qa!'",
                "Run this in a terminal and paste the output if this section still fails.",
                tags=["nvim", "neovim", "diagnostic"],
                source="Neovim detector",
            )
        ],
    )


def detect_neovim() -> Group:
    nvim = _find_executable("nvim")
    if not nvim:
        return _nvim_failure("The desktop-launched HUD could not resolve nvim. This is commonly caused by a different GUI PATH.")

    modes = {
        "n": "Normal",
        "v": "Visual/Select",
        "x": "Visual",
        "s": "Select",
        "o": "Operator-pending",
        "i": "Insert",
        "c": "Command-line",
        "t": "Terminal",
    }

    data_file = tempfile.NamedTemporaryFile(prefix="hotkey-hud-nvim-", suffix=".jsonl", delete=False)
    data_path = Path(data_file.name)
    data_file.close()
    script_file = tempfile.NamedTemporaryFile(prefix="hotkey-hud-nvim-", suffix=".lua", mode="w", delete=False)
    script_path = Path(script_file.name)
    output_path = json.dumps(str(data_path))
    script_file.write(
        "local modes={'n','v','x','s','o','i','c','t'}\n"
        "local seen={}\nlocal out={}\n"
        "for _,mode in ipairs(modes) do\n"
        "  local lists={{kind='global',maps=vim.api.nvim_get_keymap(mode)},{kind='buffer',maps=vim.api.nvim_buf_get_keymap(0,mode)}}\n"
        "  for _,list in ipairs(lists) do\n"
        "    for _,m in ipairs(list.maps) do\n"
        "      local k=mode..'\\0'..m.lhs..'\\0'..(m.desc or '')..'\\0'..(m.rhs or '')..'\\0'..list.kind\n"
        "      if not seen[k] then\n"
        "        seen[k]=true\n"
        "        table.insert(out,vim.json.encode({mode=mode,lhs=m.lhs,desc=m.desc or '',rhs=m.rhs or '',scope=list.kind}))\n"
        "      end\n"
        "    end\n"
        "  end\n"
        "end\n"
        f"vim.fn.writefile(out,{output_path})\n"
    )
    script_file.close()

    try:
        # Lazy.nvim/LazyVim schedules some setup after startup. Give those jobs a
        # short chance to run, then query the actual loaded mapping tables.
        result = _run_result(
            nvim,
            "--headless",
            "+lua vim.wait(700)",
            "+lua dofile(" + json.dumps(str(script_path)) + ")",
            "+qa!",
            timeout=15.0,
        )
        if result is None:
            return _nvim_failure("Could not launch Neovim.", nvim)

        raw = data_path.read_text(encoding="utf-8", errors="replace") if data_path.exists() else ""
        if not raw.strip():
            detail = result.stderr.strip() or result.stdout.strip() or f"Neovim exited with status {result.returncode} without mapping data."
            return _nvim_failure(detail, nvim)

        by_mode_scope: dict[str, dict[str, list[Entry]]] = {}
        total = 0
        for idx, line in enumerate(raw.splitlines()):
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
            mode_label = modes.get(mode, mode)
            detail = rhs or ("Lua callback" if not desc else desc)
            entry = Entry(
                f"nvim-{idx}",
                title,
                lhs,
                detail,
                "shortcut",
                ["nvim", "neovim", mode, mode_label.lower(), scope],
                source=f"Neovim · {mode_label} · {scope}",
            )
            by_mode_scope.setdefault(mode, {}).setdefault(scope, []).append(entry)
            total += 1

        if not total:
            return _nvim_failure("Neovim returned mapping data, but none of it could be parsed.", nvim)

        mode_groups: list[Group] = []
        for mode, mode_label in modes.items():
            scopes = by_mode_scope.get(mode)
            if not scopes:
                continue
            scope_groups = [
                Group(
                    f"nvim-{mode}-{scope}",
                    f"{scope.title()} ({len(entries)})",
                    "·",
                    f"{mode_label} mode {scope} mappings",
                    sorted(entries, key=lambda e: (e.value.lower(), e.title.lower())),
                )
                for scope, entries in sorted(scopes.items(), key=lambda item: (0 if item[0] == "global" else 1, item[0]))
            ]
            count = sum(len(entries) for entries in scopes.values())
            mode_groups.append(
                Group(
                    f"nvim-mode-{mode}",
                    f"{mode_label} ({count})",
                    mode.upper(),
                    f"Neovim {mode_label.lower()} mode mappings",
                    children=scope_groups,
                )
            )
        return Group(
            "nvim-live",
            f"Neovim · detected ({total})",
            "N",
            f"Loaded mappings from {nvim}, grouped by mode and scope",
            children=mode_groups,
        )
    finally:
        data_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)


def _unquote_alias(value: str) -> str:
    value = value.strip()
    try:
        parsed = shlex.split(value, posix=True)
        if len(parsed) == 1:
            return parsed[0]
    except ValueError:
        pass
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _alias_category(name: str, value: str) -> tuple[str, str, str]:
    text = f"{name} {value}".lower()
    if "git " in text or (name.startswith("g") and any(word in text for word in ("git", "status", "commit", "checkout", "branch"))):
        return "git", "Git", "⑂"
    if any(word in text for word in ("docker", "podman", "compose")):
        return "containers", "Containers", "▧"
    if any(word in text for word in ("kubectl", "k9s", "helm", "terraform", "aws ", "gh ", "pnpm", "npm ", "yarn ", "mise ")):
        return "dev", "Dev tools", ">_"
    if value.startswith(("cd ", "ls", "eza", "pwd", "pushd", "popd")):
        return "navigation", "Navigation & files", "⌂"
    if any(word in text for word in ("systemctl", "journalctl", "sudo ", "apt ", "pacman", "dnf ")):
        return "system", "System", "⚙"
    return "other", "Other aliases", "…"


def detect_zsh_aliases() -> Group | None:
    path = Path.home() / ".zshrc"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    categories: dict[str, tuple[str, str, list[Entry]]] = {}
    total = 0
    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line.startswith("alias "):
            continue
        rest = line[6:].strip()
        global_alias = False
        if rest.startswith("-g "):
            global_alias = True
            rest = rest[3:].strip()
        if "=" not in rest:
            continue
        name, value = rest.split("=", 1)
        name = name.strip()
        if not name or any(ch.isspace() for ch in name):
            continue
        value = _unquote_alias(value)
        category_id, title, icon = _alias_category(name, value)
        if category_id not in categories:
            categories[category_id] = (title, icon, [])
        categories[category_id][2].append(
            Entry(
                f"zsh-alias-{line_no}-{_slug(name)}",
                name,
                value,
                f"Alias defined in ~/.zshrc line {line_no}",
                tags=["zsh", "alias", name, category_id],
                source="~/.zshrc" + (" · global alias" if global_alias else ""),
            )
        )
        total += 1
    if not total:
        return None
    order = ["navigation", "git", "containers", "dev", "system", "other"]
    children = [
        Group(
            f"zsh-aliases-{category_id}",
            f"{categories[category_id][0]} ({len(categories[category_id][2])})",
            categories[category_id][1],
            "Aliases grouped by likely purpose",
            sorted(categories[category_id][2], key=lambda e: e.title.lower()),
        )
        for category_id in order
        if category_id in categories
    ]
    return Group(
        "zsh-aliases",
        f"Zsh aliases · detected ({total})",
        "Z",
        "Custom aliases parsed safely from ~/.zshrc without sourcing or executing it",
        children=children,
    )


def detect_groups() -> list[Group]:
    return [g for g in (detect_kde_global(), detect_tmux(), detect_neovim(), detect_zsh_aliases()) if g]
