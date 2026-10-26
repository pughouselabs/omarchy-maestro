# Installation

Maestro needs Python 3.10 or newer. Its Python runtime uses only the standard
library. Keep Solaar and logiops stopped while Maestro is using the mouse.

## Any Linux distribution

Recommended: install the command line tools with pipx, which keeps Maestro in
an isolated environment:

```sh
pipx install .
```

This optional pip/pipx path uses build isolation: it downloads the
`setuptools>=68` and `wheel` build backend from PyPI once per isolated build
environment. It is separate from the source-only Omarchy plugin installation.
For a build without those downloads, use trusted distro-provided setuptools
and wheel in your virtual environment, then run:

```sh
python -m pip install --no-build-isolation .
```

That command requires the build tools to be installed already. The Arch recipe
below uses the distro build tools with `--no-isolation` instead.

If pipx is unavailable, run `packaging/install.sh`. It creates a dedicated
virtual environment at `${XDG_DATA_HOME:-~/.local/share}/maestro/venv` and
links `maestro` and `maestrod` into `~/.local/bin`. Ensure that directory is
on `PATH`. This avoids system Python installs blocked by PEP 668. The installer
also prints the `sudo` commands for the udev and module-load files; it never
runs sudo itself. The hidraw rule `70-maestro.rules` is required. The uinput
rule `71-maestro-uinput.rules` and the module-load file are optional and only
needed by `maestrod`; skip them for widget-only or command-line use. The script
installs for the current user only and refuses
`DESTDIR`; to package Maestro, use the Arch PKGBUILD below or build a wheel with
`python -m build`.

## Arch Linux

This is a local-source recipe, not an AUR upload or a downloaded release
archive. Its checked-in `SKIP` is a placeholder because the archive depends on
your chosen local commit; a checksum of an archive containing that same
PKGBUILD cannot be embedded in itself. Replace the placeholder with the real
SHA-256 before building or distributing the recipe. From the repository root,
after committing the source you want to package:

```sh
git archive --format=tar --prefix=maestro-0.3.2/ HEAD | gzip -n > packaging/arch/maestro-0.3.2.tar.gz
cd packaging/arch
sha256sum maestro-0.3.2.tar.gz
updpkgsums
makepkg --printsrcinfo > .SRCINFO
makepkg --verifysource
makepkg -si
```

`updpkgsums` (from pacman-contrib) writes the computed digest into PKGBUILD.
Review it against the printed SHA-256. Keep that PKGBUILD beside the archive;
`makepkg --verifysource` will then reject a changed archive. No mutable URL is
used. Undo the local packaging edits with git after keeping any build artifacts
you need.

The package activates only the required hidraw rule
(`/usr/lib/udev/rules.d/70-maestro.rules`). The optional uinput files for
`maestrod` are installed inactive under `/usr/share/maestro-mouse/optional/`.
To use the service, enable them:

```sh
sudo install -D -m 0644 /usr/share/maestro-mouse/optional/71-maestro-uinput.rules /etc/udev/rules.d/71-maestro-uinput.rules
sudo install -D -m 0644 /usr/share/maestro-mouse/optional/maestro-uinput.conf /etc/modules-load.d/maestro-uinput.conf
sudo modprobe uinput
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Remove those two files from `/etc` (and reload udev) to turn uinput access off
again; removing the package does not remove them.

## Omarchy bar widget and settings app

Install the plugin from the Omarchy plugin marketplace, or clone it into
`~/.config/omarchy/plugins/io.github.pughouselabs.maestro`, as described in the
repository README. The command line installation alone does not install the
widget. Back up shell configuration before editing it.

## Remove

If you installed with pipx, remove the package with:

```sh
pipx uninstall maestro-mouse
```

`packaging/uninstall.sh` does the same when it finds the pipx package, removes
the fallback virtual environment and its command links, and removes the window
rule. It prints the `sudo` commands that remove both udev rule files and the
module-load file; run them and reload udev. Remove the Omarchy plugin
separately with
`omarchy plugin remove io.github.pughouselabs.maestro` (see the README for the
complete removal steps).
