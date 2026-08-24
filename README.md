# Hotkey HUD

A keyboard-first, searchable popup for the shortcuts and commands you never remember.

Hotkey HUD is built for Linux desktops, especially KDE Plasma / Wayland. It combines live shortcut discovery with a curated command cheat sheet, keeps everything organized in a nested sidebar, and is designed to open quickly from a global keyboard shortcut.

It can show:

- KDE / Plasma global shortcuts
- Neovim mappings
- tmux bindings
- Zsh aliases
- Firefox / Chrome shortcuts
- Docker, systemd, GitHub Actions, Git, AWS, Terraform and pnpm commands
- Linux troubleshooting recipes and shell snippets
- your own YAML-defined shortcuts and commands

## Features

### Live discovery

Hotkey HUD can discover local configuration and runtime shortcuts from:

- **KDE / Plasma** — reads `~/.config/kglobalshortcutsrc`, groups shortcuts by purpose and owning component, and detects exact shortcut conflicts
- **tmux** — reads `tmux list-keys`, keeps common tables prominent, and moves obscure/internal tables into an advanced group
- **Neovim** — launches your real Neovim configuration headlessly and reads loaded mappings across modes and scopes
- **Zsh** — safely parses aliases from `~/.zshrc` without sourcing or executing it

Neovim also includes a curated **Essentials I forget** section with common editing/navigation commands such as selections, motions, paragraph jumps, word/text-object operations, commenting, search-next/search-previous, definitions/references, scrolling, indentation and repeat.

If Neovim detection fails, the HUD shows a useful diagnostic instead of silently hiding the section.

### Fast cached startup

Live detection is cached under:

```text
~/.cache/hotkey-hud/detected.json
```

The first successful run performs the expensive discovery work in the background and stores the result. Later launches load the cached shortcut data immediately and refresh it silently in the background.

If the fresh scan produces the same data as the cache, the UI is not rebuilt. This keeps subsequent launches fast and avoids unnecessary refresh hitches.

Use **Ctrl+R** or the **Refresh** button when you want to force a fresh scan.

### Search

Search covers shortcut keys, titles, commands, descriptions, sources and tags. Results are ranked so exact key/title matches appear before weaker matches.

Supported filters include:

```text
source:kwin
app:nvim
kind:shortcut
key:meta+f
```

Search rendering is debounced so typing does not rebuild the entire result view on every keystroke.

### Favorites

Every shortcut or command can be bookmarked with the star button. Bookmarks are stored locally and exposed through a dedicated **Favorites** section.

### Persistent UI state

Hotkey HUD remembers local UI state between launches, including:

- selected section/group
- expanded/collapsed groups
- search text
- sidebar width
- normal window geometry
- scroll position for each section/group/search view
- favorites

### Keyboard navigation

Search and content controls:

- `/`, `Ctrl+K` or `Ctrl+L` — focus search
- `Esc` — clear search; press again to close the HUD
- `Ctrl+R` — refresh detected shortcuts
- `Ctrl+Up` / `Ctrl+Down` — scroll the right-hand content pane
- `Ctrl+Enter` — toggle the first visible content group
- `F11` — toggle fullscreen

Sidebar navigation:

- click the sidebar or press **F6** to focus it
- `Up` / `Down` — move through navigation items
- `Left` — collapse the current branch, or move to its parent
- `Right` — expand the current branch
- `Enter` — activate/select the highlighted item

The HUD deliberately does not consume KDE window-management shortcuts such as **Meta+Arrow**.

### KDE / Wayland window behavior

The app uses a normal KWin-managed window rather than a custom frameless surface, so normal KDE behavior works as expected:

- maximize / restore
- quick tiling
- moving between screens/workspaces
- standard window decorations
- KDE/Wayland activation rules

The interior UI still uses a translucent/glassy dark style.

### Single-instance behavior

Only one HUD instance is kept alive.

If the global launcher shortcut is pressed while Hotkey HUD is already running, the second invocation signals the existing process instead of opening another copy. The launcher forwards Wayland/XDG activation information so the existing window can request focus from KWin.

## Built-in command library

The bundled library includes shortcuts and commands for common developer workflows such as:

- systemd / journalctl
- Docker / Docker Compose
- Git and worktrees
- GitHub Actions and self-hosted runners
- AWS CLI
- Terraform
- pnpm / Node.js
- Linux networking, process, disk and log troubleshooting
- clipboard / pipe recipes
- quick debugging recipes

Commands expose a **Copy** button. Keyboard shortcuts do not, because copying a key combination is rarely useful.

Explicitly safe commands can optionally expose **Run**. Dangerous commands are never given a Run button.

## Install on Ubuntu / Ubuntu Studio

```bash
sudo apt install -y python3-venv git

git clone https://github.com/gmmpb/hotkey-hud.git ~/.local/share/hotkey-hud-src

python3 -m venv ~/.local/share/hotkey-hud
~/.local/share/hotkey-hud/bin/pip install ~/.local/share/hotkey-hud-src

mkdir -p ~/.local/bin
ln -sf ~/.local/share/hotkey-hud/bin/hotkey-hud ~/.local/bin/hotkey-hud

hotkey-hud
```

## Update

```bash
cd ~/.local/share/hotkey-hud-src
git pull
~/.local/share/hotkey-hud/bin/pip install .
hotkey-hud
```

## Bind it globally in KDE Plasma

1. Open **System Settings → Keyboard → Shortcuts**.
2. Add a command/application shortcut for `hotkey-hud`.
3. Assign a key such as `Meta+/`.

Pressing the shortcut again reuses and activates the existing HUD instance.

## Custom commands and shortcuts

Create:

```text
~/.config/hotkey-hud/config.yaml
```

Example:

```yaml
sections:
  - id: mine
    title: Mine
    icon: "★"
    groups:
      - id: wari
        title: Wari
        icon: "W"
        entries:
          - title: Local checks
            value: mise run check
            description: Run the local validation suite
            tags: [wari, dev]
            source: Wari
```

Your configuration is loaded in addition to the built-in library.

Entries support fields such as:

```yaml
kind: command     # command | shortcut
action: copy      # copy | run
danger: false
source: My tool
tags: [dev, local]
```

## Safety

The default behavior is **copy**, not execution.

A command only receives a Run button when its entry explicitly specifies:

```yaml
action: run
danger: false
```

Receipt/password/credential handling is not part of the app; Hotkey HUD only reads local shortcut/configuration information required for its own display.

## Current limitations

- Browser shortcuts are curated rather than dynamically extracted from Firefox/Chrome internals.
- Neovim mappings that are only created after opening a specific filetype, buffer or lazy-loaded plugin may not exist during headless discovery.
- Zsh alias parsing currently focuses on aliases declared directly in `~/.zshrc`; sourced alias files/plugin aliases are not fully followed yet.
- Wayland prevents applications from arbitrarily stealing focus, so activation relies on the launcher/session providing a valid user activation token.
- The UI currently rebuilds result cards after a search pause rather than virtualizing/reusing every row.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
hotkey-hud
```

Main implementation areas:

```text
hotkey_hud/default.yaml          built-in command/shortcut library
hotkey_hud/detectors.py          base live detectors
hotkey_hud/enhanced_detectors.py enhanced detector grouping/curation
hotkey_hud/fast_app.py           main HUD behavior
hotkey_hud/perf_app.py           search/scroll performance layer
hotkey_hud/kde_perf_app.py       KDE/KWin window behavior
hotkey_hud/cached_app.py         cache, sidebar focus and single-instance activation
hotkey_hud/style.qss             UI styling
```

## Ideas for later

- active-window-aware context/prioritization
- deeper browser shortcut discovery
- recursively parse safe literal Zsh alias include files
- command placeholders with inline inputs
- alias/executable health checks
- KRunner integration
- more aggressive result virtualization if the detected shortcut set grows very large

## License

MIT
