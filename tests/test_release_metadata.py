"""Keep the public plugin identity, release metadata and setup contract aligned."""

import json
import re
import unittest
from pathlib import Path

import isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
IDENT = "io.github.pughouselabs.maestro"
VERSION = "0.3.2"


class ReleaseMetadataTests(unittest.TestCase):
    def test_plugin_packaging_and_help_use_the_same_identity(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["id"], IDENT)
        self.assertEqual(manifest["author"], "Pughouse Labs")
        for name in ("BarWidget.qml", "Panel.qml"):
            self.assertIn(f'moduleName: "{IDENT}"', (ROOT / name).read_text())
        desktop = ROOT / "packaging/desktop" / f"{IDENT}.desktop"
        self.assertIn(f"Icon={IDENT}", desktop.read_text())
        self.assertTrue((desktop.parent / f"{IDENT}.svg").exists())
        self.assertEqual(len(list(desktop.parent.glob("*.desktop"))), 1)
        help_text = (ROOT / "app/HelpPanel.qml").read_text()
        self.assertIn("Pughouse Labs", help_text)
        self.assertIn("https://github.com/pughouselabs/omarchy-maestro/issues", help_text)
        self.assertIn(
            'authors = [{ name = "Pughouse Labs" }]', (ROOT / "pyproject.toml").read_text()
        )
        self.assertIn("Copyright (c) 2026 Pughouse Labs", (ROOT / "LICENSE").read_text())
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text()
            except UnicodeError:
                continue
            owners = re.findall(r"https://github.com/([^/]+)/omarchy-maestro", text)
            self.assertTrue(all(owner == "pughouselabs" for owner in owners), str(path))

    def test_release_versions_and_upgrade_instructions(self):
        self.assertEqual(json.loads((ROOT / "manifest.json").read_text())["version"], VERSION)
        for name, marker in (
            ("pyproject.toml", f'version = "{VERSION}"'),
            ("app/AppState.qml", f'versionString:"{VERSION}"'),
            ("packaging/arch/PKGBUILD", f"pkgver={VERSION}"),
            ("packaging/arch/.SRCINFO", f"pkgver = {VERSION}"),
            ("CHANGELOG.md", f"## [{VERSION}]"),
        ):
            self.assertIn(marker, (ROOT / name).read_text())
        readme = (ROOT / "README.md").read_text()
        upgrade = readme.split("### Upgrading from 0.3.0\n", 1)[1].split("###", 1)[0]
        for marker in ("plugin folder", "bar entry", IDENT, "roll back"):
            self.assertIn(marker, upgrade)

    def test_ci_has_immutable_actions_and_bounded_readonly_jobs(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        actions = re.findall(r"uses: ([^\s]+)", ci)
        self.assertEqual(len(actions), 2)
        for action in actions:
            self.assertRegex(action, r"^actions/(?:checkout|setup-python)@[0-9a-f]{40}$")
        self.assertIn("permissions:\n  contents: read", ci)
        self.assertIn("timeout-minutes: 15", ci)
        for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
            self.assertIn(f"'{version}'", ci)

    def test_required_hidraw_optional_setup_and_separate_image_license(self):
        readme = (ROOT / "README.md").read_text()
        requirements = readme.split("## Requirements", 1)[1].split("## Install", 1)[0]
        self.assertIn("stock Omarchy", requirements)
        self.assertIn("required for the\n  widget to read the mouse", requirements)
        self.assertIn("nothing runs sudo automatically", requirements)
        self.assertIn(
            "**Optional, only for the background service (remapping and gestures):**", readme
        )
        license_text = readme.split("## License\n", 1)[1]
        for marker in (
            "MIT",
            "Device renders",
            "silhouette",
            "screenshots",
            "preview.png",
            "CC BY-NC 4.0",
            "danish_blends",
        ):
            self.assertIn(marker, license_text)

    def test_optional_build_provenance_and_local_checksum_procedure(self):
        readme = (ROOT / "README.md").read_text()
        install = (ROOT / "docs/install.md").read_text()
        self.assertIn("PyPI once per isolated build environment", readme)
        for marker in (
            "setuptools>=68",
            "wheel",
            "once per isolated build",
            "--no-build-isolation",
            "SKIP",
            "git archive --format=tar",
            "gzip -n",
            "sha256sum maestro-0.3.2.tar.gz",
            "updpkgsums",
            "makepkg --verifysource",
        ):
            self.assertIn(marker, install)
        recipe = (ROOT / "packaging/arch/PKGBUILD").read_text()
        self.assertIn('source=("maestro-${pkgver}.tar.gz")', recipe)
        self.assertNotRegex(recipe, r"source=\(.*https?://")

    def test_widget_only_setup_never_grants_uinput(self):
        def rules(name):
            text = (ROOT / "packaging/udev" / name).read_text()
            return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]

        required = rules("70-maestro.rules")
        self.assertTrue(required and all('SUBSYSTEM=="hidraw"' in line for line in required))
        self.assertFalse(any("uinput" in line for line in required))
        self.assertEqual(
            rules("71-maestro-uinput.rules"),
            ['KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"'],
        )
        recipe = (ROOT / "packaging/arch/PKGBUILD").read_text()
        self.assertIn('"$pkgdir/usr/lib/udev/rules.d/70-maestro.rules"', recipe)
        self.assertNotIn("usr/lib/udev/rules.d/71", recipe)
        self.assertNotIn("usr/lib/modules-load.d", recipe)
        self.assertIn('"$pkgdir/usr/share/$pkgname/optional/71-maestro-uinput.rules"', recipe)
        readme = (ROOT / "README.md").read_text()
        required_step = readme.split("**Required, for the widget", 1)[1].split("**Optional", 1)[0]
        self.assertIn("/etc/udev/rules.d/70-maestro.rules", required_step)
        self.assertNotIn("uinput", required_step.split("```bash", 1)[1])
        for path in ("README.md", "docs/install.md", "packaging/uninstall.sh"):
            self.assertIn("71-maestro-uinput.rules", (ROOT / path).read_text(), path)
        install = (ROOT / "packaging/install.sh").read_text()
        self.assertLess(install.index("70-maestro.rules"), install.index("Optional"))
        self.assertGreater(install.index("71-maestro-uinput.rules"), install.index("Optional"))
        self.assertIn("71-maestro-uinput.rules", (ROOT / "SECURITY.md").read_text())

    def test_upgrade_notes_update_code_first_and_explain_rollback(self):
        readme = (ROOT / "README.md").read_text()
        upgrade = readme.split("### Upgrading from 0.3.0", 1)[1].split("\n### ", 1)[0]
        first = upgrade.strip().splitlines()[0]
        self.assertIn("Update the code first", first)
        self.assertIn("omarchy plugin update", upgrade)
        self.assertIn("git pull", upgrade)
        self.assertIn("To roll back to 0.3.0", upgrade)
        self.assertIn("git checkout", upgrade)

    def test_dynamic_bar_tooltip_uses_explicit_plain_text(self):
        bar = (ROOT / "BarWidget.qml").read_text()
        self.assertIn("text: pillTip.text; textFormat: Text.PlainText", bar)
        self.assertIn("MX mouse not connected", bar)
