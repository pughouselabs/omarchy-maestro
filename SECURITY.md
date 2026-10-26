# Security policy

Maestro is an early-stage project. Please report suspected security issues
privately through GitHub's private vulnerability reporting (the repository's
**Security** tab, then **Report a vulnerability**) rather than posting
exploitable details in a public issue. Include the affected version, operating system, reproduction
steps, and impact. Do not include mouse serial numbers or other personal data.

There is no guaranteed response or patch timeline yet. Please allow time for
assessment and a fix before public disclosure.

The optional `maestrod` service needs access to `/dev/uinput` to create virtual
input events. The separate, optional udev rule `71-maestro-uinput.rules` grants
that device to the active seat user, which means processes running as that
user can inject input. This is the same security trade-off made by tools such
as Steam and input-remapper. The required rule `70-maestro.rules` grants only
Logitech hidraw access and never `/dev/uinput`, so a widget-only or
command-line setup does not get the input privilege. The Arch package ships
the uinput rule inactive.

Maestro keeps a private record of the mouse buttons it diverted in
`~/.local/state/maestro/diversions.json` (mode 0600 in a 0700 folder). It
stores only a SHA-256 hash of each mouse's unit ID, never the ID itself, and
refuses to read or write the record through a symbolic link, a special file or
a file owned by another user.
