import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeOutput

from maestro.daemon.actions import Actions, desktop_name
from maestro.daemon.uinput import EVENT, UI_DEV_CREATE, UI_DEV_DESTROY, UInput, key_code


class ActionTests(unittest.TestCase):
    def test_chord_hold_release_and_mouse_drag(self):
        output = FakeOutput()
        actions = Actions(output)
        release = actions.begin({"type": "key", "keys": ["CTRL", "C"]})
        self.assertEqual(output.events, [("press", 29), ("press", 46)])
        release()
        release()
        self.assertEqual(output.events[-2:], [("release", 46), ("release", 29)])
        self.assertFalse(output.held)
        release = actions.begin({"type": "mouse", "button": "middle"})
        self.assertIn(274, output.held)
        release()
        self.assertFalse(output.held)

    def test_command_argv_has_no_shell_and_children_are_reaped(self):
        children = []

        def popen(argv, **kwargs):
            self.assertEqual(argv, ["printf", "$(touch forbidden)"])
            self.assertNotIn("shell", kwargs)
            child = SimpleNamespace(poll=lambda: 0)
            children.append(child)
            return child

        actions = Actions(FakeOutput(), popen=popen)
        actions.execute({"type": "command", "argv": ["printf", "$(touch forbidden)"]})
        actions.reap()
        self.assertEqual(len(children), 1)
        self.assertFalse(actions.children)

    def test_desktop_detection(self):
        self.assertEqual(desktop_name({"HYPRLAND_INSTANCE_SIGNATURE": "example"}), "hyprland")
        self.assertEqual(desktop_name({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}), "gnome")
        self.assertEqual(desktop_name({"XDG_CURRENT_DESKTOP": "KDE"}), "kde")
        self.assertEqual(desktop_name({}), "unsupported")

    def test_hyprland_lua_and_stock_fallback(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0)

        actions = Actions(FakeOutput(), desktop="hyprland", run=run)
        actions.desktop_action("workspace_next")
        self.assertEqual(calls, [["hyprctl", "dispatch", 'hl.dsp.focus({workspace="e+1"})']])
        calls.clear()

        def legacy(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=1 if len(argv) == 3 else 0)

        actions.run = legacy
        actions.desktop_action("workspace_previous")
        self.assertEqual(calls[-1], ["hyprctl", "dispatch", "workspace", "e-1"])

    def test_omarchy_commands_and_other_desktops_require_an_extension(self):
        output = FakeOutput()
        calls = []
        actions = Actions(
            output,
            desktop="hyprland",
            run=lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0),
        )
        actions.desktop_action("menu")
        self.assertEqual(calls, [["omarchy-menu", "toggle", "root"]])
        actions.desktop = "gnome"
        with self.assertRaisesRegex(RuntimeError, "Omarchy/Hyprland only"):
            actions.desktop_action("workspace_previous")
        actions.desktop_handler = lambda action: calls.append([action])
        actions.desktop_action("workspace_next")
        self.assertEqual(calls[-1], ["workspace_next"])

    def test_wheel_modes_and_zoom_releases_modifier_on_failure(self):
        output = FakeOutput()
        actions = Actions(output, desktop="generic")
        actions.wheel("tabs", -1, {})
        actions.wheel("volume", 1, {})
        self.assertEqual(
            output.events,
            [
                ("press", 29),
                ("press", 104),
                ("release", 104),
                ("release", 29),
                ("press", 115),
                ("release", 115),
            ],
        )
        with patch.object(output, "scroll", side_effect=OSError("fake input failure")):
            with self.assertRaises(OSError):
                actions.wheel("zoom", 1, {})
        self.assertFalse(output.held)


class UInputTests(unittest.TestCase):
    def test_ioctl_setup_events_reference_counts_and_destroy_with_fake_fd(self):
        writes = []
        ioctls = []
        with (
            patch("maestro.daemon.uinput.os.open", return_value=123),
            patch("maestro.daemon.uinput.os.close") as close,
            patch(
                "maestro.daemon.uinput.fcntl.ioctl", side_effect=lambda *args: ioctls.append(args)
            ),
            patch(
                "maestro.daemon.uinput.os.write",
                side_effect=lambda fd, data: writes.append(data) or len(data),
            ),
        ):
            output = UInput()
            output.press(29)
            output.press(29)
            output.release(29)
            self.assertEqual(len(writes), 1)
            output.release(29)
            output.chord(["SUPER", "D"])
            output.press(274)
            output.close()
            output.close()
            close.assert_called_once_with(123)
        self.assertIn((123, UI_DEV_CREATE), ioctls)
        self.assertIn((123, UI_DEV_DESTROY), ioctls)
        events = [EVENT.unpack(data[: EVENT.size])[2:] for data in writes]
        self.assertEqual(events[:2], [(1, 29, 1), (1, 29, 0)])
        self.assertEqual(events[-2:], [(1, 274, 1), (1, 274, 0)])

    def test_setup_failure_closes_fd_before_diversion(self):
        with (
            patch("maestro.daemon.uinput.os.open", return_value=123),
            patch("maestro.daemon.uinput.os.close") as close,
            patch("maestro.daemon.uinput.fcntl.ioctl", side_effect=PermissionError("denied")),
        ):
            with self.assertRaisesRegex(OSError, "uinput access"):
                UInput()
            close.assert_called_once_with(123)

    def test_key_names_are_validated_without_system_headers_at_runtime(self):
        self.assertEqual(key_code("KEY_LEFTCTRL"), key_code("Ctrl"))
        self.assertEqual(key_code("KP6"), 77)
        with self.assertRaises(ValueError):
            key_code("does-not-exist")
