# Security policy

Maestro is an early-stage project. Please report suspected security issues
privately through GitHub's private vulnerability reporting (the repository's
**Security** tab, then **Report a vulnerability**) rather than posting
exploitable details in a public issue. Include the affected version, operating system, reproduction
steps, and impact. Do not include mouse serial numbers or other personal data.

There is no guaranteed response or patch timeline yet. Please allow time for
assessment and a fix before public disclosure.

The optional `maestrod` service needs access to `/dev/uinput` to create virtual
input events. The udev rule grants that device to the active seat user, which
means processes running as that user can inject input. This is the same
security trade-off made by tools such as Steam and input-remapper. The
`/dev/uinput` permission is only needed when running `maestrod`; the regular
`maestro` command line does not need it.
