# Supported MX mice

Maestro checks the receiver's paired-device kind, or the Bluetooth device type,
before reading mouse features. It only enables writes for the MX families below.
An unknown Logitech mouse on a receiver appears as `unsupported` in
`maestro status --all`. Direct Bluetooth nodes are probed only when their
product ID is a verified MX mouse ID or their system name strictly matches an
MX model. Keyboards and gaming receivers are skipped.

The feature column describes the HID++ feature families Maestro can read when
the mouse advertises them. It is an expectation for community testing, not a
claim that every listed feature is present in every firmware version. Battery
uses 0x1000 or 0x1004; DPI uses 0x2201 or 0x2202; SmartShift uses 0x2110 or
0x2111; hi-res wheel uses 0x2121; thumb wheel uses 0x2150; buttons use 0x1B04.
All features are discovered at runtime.

| Model | Expected connection | Feature families to check | Test status |
|---|---|---|---|
| MX Master | Unifying, Bluetooth | Battery, DPI, SmartShift, wheel, buttons | Expected, needs tester |
| MX Master 2S | Unifying, Bluetooth | Battery, DPI, SmartShift, wheel, buttons | Tested on Unifying; Bluetooth needs tester |
| MX Master 3 | Unifying, Bluetooth | Battery, DPI, SmartShift, wheel, thumb wheel, buttons | Expected, needs tester |
| MX Master 3S | Bolt, Bluetooth | Battery, extended DPI, enhanced SmartShift, wheel, thumb wheel, buttons | Expected, needs tester |
| MX Master 4 | Bolt, Bluetooth | Battery, extended DPI, enhanced SmartShift, wheel, thumb wheel, buttons | Expected, needs tester |
| MX Anywhere 2 | Unifying, Bluetooth | Battery, DPI, wheel, buttons | Expected, needs tester |
| MX Anywhere 2S | Unifying, Bluetooth | Battery, DPI, wheel, buttons | Expected, needs tester |
| MX Anywhere 3 | Unifying, Bluetooth | Battery, DPI, SmartShift, wheel, buttons | Expected, needs tester |
| MX Anywhere 3S | Bolt, Bluetooth | Battery, extended DPI, SmartShift, wheel, buttons | Expected, needs tester |
| MX Vertical | Unifying, Bluetooth | Battery, DPI, wheel, buttons | Expected, needs tester |
| MX Ergo | Unifying, Bluetooth | Battery, DPI, wheel, buttons | Expected, needs tester |
| MX Ergo S | Bolt, Bluetooth | Battery, DPI, wheel, buttons | Expected, needs tester |

Only the MX Master 2S on a Unifying receiver has been tested on hardware.
Its observed features are battery 0x1000, DPI 0x2201, SmartShift 0x2110,
hi-res wheel 0x2121, and controls 0x1B04. The physical thumb wheel does not
advertise 0x2150 on this unit.

## Send a model report

1. Stop any running Solaar or logiops daemon, then connect and wake the mouse.
2. Run `bin/maestro diagnose --json` and paste the output into a GitHub issue.
3. Include the model name, connection type, desktop, which reads worked, and
   which setting changes you tried. Do not include a device serial number or
   unit ID from another tool.

`diagnose` includes receiver type, wireless/product ID, HID++ version, feature
IDs and versions, button capabilities, and battery source. It does not read
serial numbers or unit IDs. On a receiver shared with a keyboard, Maestro reads
the receiver's pairing records but never sends HID++ requests to the keyboard.

Use `bin/maestro status --all` to see an unknown receiver mouse marked
`unsupported`. Unknown mice cannot be changed by the CLI. Use `--mouse N` or
`--device "MX Master 3S"` to select one mouse; a receiver path alone can be
ambiguous when it carries several mice. The more precise form is
`--device /dev/hidraw13:1` for slot 1.
