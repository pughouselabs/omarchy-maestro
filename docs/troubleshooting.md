# Troubleshooting

## No device found

Wake the mouse and check that it is paired to the expected receiver or
Bluetooth host. Run `maestro status` again. Confirm that the model is supported;
currently the MX Master 2S is the only model tested. For a device report, run
`maestro diagnose` and inspect the redacted output before sharing it.

## Permission denied

Confirm the udev rule `70-maestro.rules` is installed and rules were reloaded.
Unplug and reconnect the receiver or mouse, then retry. Access is granted to
the active seat user through `uaccess`; do not work around this by making device
nodes world-writable. The daemon also needs access to `/dev/uinput`.

## Solaar or logiops conflict

Maestro, Solaar, and logiops cannot own the same HID++ device at once. Stop the
Solaar daemon and logiops service before retrying Maestro. Solaar's pairing UI
may be used when Maestro is not communicating with the mouse.

## Bolt pairing

Pair a Bolt mouse with Solaar first. Once paired, close Solaar or stop its
daemon before using Maestro. Maestro does not replace receiver pairing tools.

## Bluetooth

Pair the mouse through the desktop Bluetooth settings. Wake it and ensure it is
connected before running `maestro status`. Some features can vary by transport
and mouse firmware; only features discovered and supported by that device are
available.
