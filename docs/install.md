# Installation

Maestro needs Python 3.10 or newer. Its Python runtime uses only the standard
library. Keep Solaar and logiops stopped while Maestro is using the mouse.

## Any Linux distribution

Recommended: install the command line tools with pipx, which keeps Maestro in
an isolated environment:

```sh
pipx install .
```

If pipx is unavailable, run `packaging/install.sh`. It creates a dedicated
virtual environment at `${XDG_DATA_HOME:-~/.local/share}/maestro/venv` and
links `maestro` and `maestrod` into `~/.local/bin`. Ensure that directory is
on `PATH`. This avoids system Python installs blocked by PEP 668. The installer
also prints the `sudo` commands required to install the udev and module-load
files; it never runs sudo itself. The uinput permission is only needed by
`maestrod`. The script installs for the current user only and refuses
`DESTDIR`; to package Maestro, use the Arch PKGBUILD below or build a wheel with
`python -m build`.

## Arch Linux

Create a source archive named `maestro-0.3.0.tar.gz` containing the project
root as `maestro-0.3.0/`, place it beside `packaging/arch/PKGBUILD`, then run
`makepkg -si` in that directory. Review the PKGBUILD before installation.

## Omarchy bar widget and settings app

Install the plugin from the Omarchy plugin marketplace, or clone it into
`~/.config/omarchy/plugins/io.github.nodrej.maestro`, as described in the
repository README. The command line installation alone does not install the
widget. Back up shell configuration before editing it.

## Remove

If you installed with pipx, remove the package with:

```sh
pipx uninstall maestro-mouse
```

`packaging/uninstall.sh` does the same when it finds the pipx package, removes
the fallback virtual environment and its command links, and removes the window
rule. It prints the `sudo` commands for the udev and module-load files; run
them and reload udev. Remove the Omarchy plugin separately with
`omarchy plugin remove io.github.nodrej.maestro` (see the README for the
complete removal steps).
