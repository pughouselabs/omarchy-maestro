# Troubleshooting

## No device found

Wake the mouse and check that it is paired to the expected receiver or
Bluetooth host. Run `maestro status` again. Confirm that the model is supported;
currently the MX Master 2S is the only model tested. For a device report, run
`maestro diagnose` and inspect the redacted output before sharing it.

## Permission denied

Confirm the required udev rule `70-maestro.rules` is installed and rules were
reloaded. Unplug and reconnect the receiver or mouse, then retry. Access is
granted to the active seat user through `uaccess`; do not work around this by
making device nodes world-writable. Only the background service also needs
`/dev/uinput`, which the separate optional `71-maestro-uinput.rules` grants.

## Solaar or logiops conflict

Maestro, Solaar, and logiops cannot own the same HID++ device at once. Stop the
Solaar daemon and logiops service before retrying Maestro. Solaar's pairing UI
may be used when Maestro is not communicating with the mouse.

## Maestro says Solaar is running

`maestro status` prints "Paused: Solaar is running and controls the mouse.
Close Solaar to use Maestro." (or the same for logiops), the bar widget shows
"Paused: Solaar is running", and the settings app shows the same notice.

The Maestro service has noticed another app that talks to the mouse and has
stepped aside. While paused it keeps running but leaves the mouse alone: if it
had diverted buttons it gives them back first, then it sends nothing to the
mouse and checks again about every 15 seconds. Settings changes are refused
with the same message until the other app is gone.

What to do:

1. Quit Solaar completely (including its tray icon and any copy started at
   login), or stop logiops with `sudo systemctl stop logid` (it is a
   system service).
2. Wait up to 15 seconds. Maestro finds the mouse again by itself; nothing
   needs restarting.
3. If the gesture button or thumb wheel still does nothing afterwards, Solaar
   may have left it diverted. The notice then changes to "held by another app";
   follow the next section to release it.

## Service will not start or stopped restarting

systemd allows the service at most five starts in five minutes (the first start
counts), then stops restarting it so a broken setup can never loop. See the reason with:

```bash
journalctl --user -u maestrod -n 50
```

Fix the cause it names, then start it again with
`systemctl --user reset-failed maestrod` and
`systemctl --user start maestrod`. Solaar or logiops running is not a crash;
the service waits for them instead (see above).

## Gesture button does nothing

Cause: if Maestro crashed or the computer lost power, a mouse on a receiver
can stay powered and keep a button diverted by the previous session. A normal
shutdown releases every button first. Another app (Solaar or logiops) may also
hold the button.

Before every change to a mouse, Maestro reads its unit ID again and writes only
when it matches the mouse it opened. If the ID cannot be read, the mouse is
read-only and status says "Maestro could not confirm this mouse's identity, so
it won't change its settings. Reconnect it." Turn the mouse off and on, or
unplug and replug the receiver; Maestro checks again every few seconds.

Maestro keeps a small record of the controls it diverted in
`~/.local/state/maestro/diversions.json` (or under `$XDG_STATE_HOME`). Each
mouse is identified by its model, its connection and a hash of the unit ID the
mouse reports. The hash is pseudonymous, not anonymous: the same mouse always
gives the same hash. The ID itself is never stored or shown, and
`maestro diagnose` leaves it out.

Maestro never takes a button back by itself. A record cannot show who holds a
button now, because another app may divert it the same way. On start:

- If the record shows Maestro had that button on this exact mouse and the
  button still reports the recorded flags, the notice says "Maestro may have
  left the gesture button taken during an unexpected shutdown. Choose Release
  button to fix it." The flags match, but they cannot prove Maestro still
  holds it.
- Otherwise (no record, or different flags) the
  notice says "The gesture button is held by another app (Solaar or logiops?)".

In both cases nothing is written to the mouse until you release the button.
The service keeps running: DPI, SmartShift and scrolling keep working.

What to do:

1. Close Solaar or stop logiops (or the other app), or turn the mouse off and
   on. Maestro checks busy buttons again within about 10 seconds, and again
   when the mouse reconnects or the configuration reloads.
2. If no other app is running, release the button explicitly: choose
   **Release button** under the notice in the settings app, or run
   `maestro release-buttons` (add `--mouse N` for one mouse). It acts only on
   the mouse you chose: it reads the mouse's unit ID again and refuses before
   writing anything if a different mouse (even the same model in the same
   receiver slot) now sits at that position, or if the ID cannot be read. It
   turns off
   temporary diversion on every button Maestro can divert that the running
   service does not own, plus the thumb wheel, prints what it released, and
   the service then takes the buttons over. It never changes persistent
   (onboard) settings.

If the notice says "Can't save the button record; gestures are off until this
is fixed", Maestro could not write its record (for example a full disk, or
`~/.local/state/maestro` is not a private folder owned by you). Maestro does
not divert any button it cannot record. Free some space or fix the folder;
Maestro retries within about 10 seconds.

## Bolt pairing

Pair a Bolt mouse with Solaar first. Once paired, close Solaar or stop its
daemon before using Maestro. Maestro does not replace receiver pairing tools.

## Bluetooth

Pair the mouse through the desktop Bluetooth settings. Wake it and ensure it is
connected before running `maestro status`. Some features can vary by transport
and mouse firmware; only features discovered and supported by that device are
available.
