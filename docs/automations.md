# Automations

Automations let one mouse button run a short list of actions. Put named
automations under `automations` in your Maestro config, then assign a button,
gesture direction, or custom thumb-wheel direction to an automation ID.

Run `bin/maestro catalog --json` to see ready-made actions and
`bin/maestro controls --json` to see which controls your mouse offers. Edit a
complete configuration from `bin/maestro config get`, then apply it with
`bin/maestro config apply --stdin < my-config.json`. Maestro checks the whole
file before saving it and keeps the last 20 backups. Use
`bin/maestro config backups --json` and `bin/maestro config restore NAME` to
undo a change. `bin/maestro config undo` restores the copy saved before the
most recent apply. Restore and undo each back up the current file first.
Set `MAESTRO_CONFIG_HOME` to a temporary directory to try a configuration
without touching your normal settings.

The catalog also includes gesture presets for window navigation, workspaces,
media, and zoom, plus editable templates for paste-and-send, screenshot-region,
morning-apps, and mute-and-lock. Copy a template's steps into a named automation,
then assign its ID to a control.

## Paste and send

This pastes what is already on your clipboard, waits briefly for the app to
process it, then presses Enter. It does not read the clipboard itself.

```json
{
  "automations": {
    "paste-and-send": {
      "name": "Paste and send",
      "description": "Paste the clipboard and submit it",
      "steps": [
        {"type": "key", "keys": ["CTRL", "V"]},
        {"type": "delay", "ms": 150},
        {"type": "key", "keys": ["ENTER"]}
      ]
    }
  },
  "buttons": {"back": {"type": "automation", "id": "paste-and-send"}}
}
```

## Screenshot region

This uses Omarchy's screenshot command, verified on this machine. The command
is an argument list and never passes through a shell.

```json
{
  "automations": {
    "screenshot-region": {
      "name": "Screenshot region",
      "description": "Select a region and copy the image",
      "steps": [
        {"type": "command", "argv": ["omarchy", "capture", "screenshot", "region", "copy"]}
      ]
    }
  },
  "buttons": {"mode_shift": {"type": "automation", "id": "screenshot-region"}}
}
```

## Join meeting

This example opens a meeting URL in your default browser. Replace the URL
with your own. It types a short greeting only after a delay, so check that the
meeting chat has focus before assigning the text step.

```json
{
  "automations": {
    "join-meeting": {
      "name": "Join meeting",
      "description": "Open the meeting and type a greeting",
      "steps": [
        {"type": "command", "argv": ["xdg-open", "https://example.com/meeting"]},
        {"type": "delay", "ms": 2000},
        {"type": "text", "text": "Hello, joining now."}
      ]
    }
  },
  "gesture": {"up": {"type": "automation", "id": "join-meeting"}}
}
```

The `text` step sends printable ASCII using US keyboard key positions. It
rejects accents, emoji, newlines, and other non-ASCII characters at validation.
Your desktop must use a US keyboard layout for the resulting text to match.
Each key step is released before the next step. A sequence can have 1-50
expanded steps, each delay can be 0-5000 ms, total expanded delay is at most
30 seconds, total text is at most 500 characters, and execution stops after
30 seconds. Automation references can nest at most three levels. These limits
are checked on save and while the sequence runs. One run per trigger can be
active at a time. Mouse disconnect,
daemon stop, and config reload cancel running sequences and release keys.
Maestro sends all virtual input through one input owner. A key chord finishes
before another action's chord starts, and failed key releases are retried until
the key is released. A delay over 5000 ms is also stopped if a saved automation
is changed while it is running.

An automation can refer to another automation by ID. Unknown IDs and cycles
are rejected. A `hyprland` step uses an allowed dispatcher, for example
`{"type":"hyprland","dispatcher":"workspace","arg":"e+1"}`. Maestro
builds the Lua call and sends it to `hyprctl dispatch` as one argument without
a shell. See [Configuration](configuration.md) for the allowed dispatchers and
argument forms.
