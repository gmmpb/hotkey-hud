# Hotkey HUD

A keyboard-first, searchable popup for the things you never remember:

- KDE / Plasma shortcuts
- Neovim and tmux mappings
- Firefox / Chrome shortcuts
- Docker, systemd, GitHub Actions, Git, AWS, Terraform and pnpm commands
- Linux troubleshooting recipes and shell snippets

The UI is nested and organized instead of presenting one giant cheat sheet. Commands can be copied with one click; explicitly safe entries may also expose a **Run** button.

## Features

- Fast fuzzy-ish token search across titles, commands, descriptions and tags
- Nested categories in a compact sidebar
- Copy buttons for every shortcut/command
- Live discovery of KDE global shortcuts, tmux bindings and described Neovim normal-mode mappings
- User-defined YAML additions at `~/.config/hotkey-hud/config.yaml`
- Frameless dark HUD designed for KDE Plasma / Wayland
- Keyboard controls: `/` or `Ctrl+L` focuses search, `Esc` closes

## Install on Ubuntu / Ubuntu Studio

```bash
sudo apt install python3-pip python3-venv
python3 -m venv ~/.local/share/hotkey-hud/venv
~/.local/share/hotkey-hud/venv/bin/pip install .
mkdir -p ~/.local/bin
ln -sf ~/.local/share/hotkey-hud/venv/bin/hotkey-hud ~/.local/bin/hotkey-hud
hotkey-hud
```

If PySide6 installation via pip is undesirable, distro Qt/Python packaging can be used later.

## Bind it globally in KDE Plasma

1. Open **System Settings → Keyboard → Shortcuts**.
2. Add a new command/application shortcut for `hotkey-hud`.
3. Assign a key such as `Meta+/` or `Meta+?`.

## Custom commands

Create `~/.config/hotkey-hud/config.yaml`:

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
```

Your file is loaded in addition to the built-in library.

## Safety

The default behavior is **copy**, not execution. A command only gets a Run button when the data entry explicitly has `action: run` and is not marked dangerous.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
hotkey-hud
```

## Roadmap

- Active-window detection and automatic app context
- Better KDE / Konsole / Dolphin extraction
- Firefox/Chrome extension hotkey discovery
- Command placeholders with inline input fields
- Favorite/recent commands
- Config editor
- KRunner integration

## License

MIT
