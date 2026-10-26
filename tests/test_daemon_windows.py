import socket
import unittest
from types import SimpleNamespace

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro.daemon.windows import Windows


class WindowTests(unittest.TestCase):
    def test_hyprland_active_class_and_failure_clears_previous_profile(self):
        results = iter(
            [
                SimpleNamespace(returncode=0, stdout='{"class":"code","title":"main.py"}'),
                SimpleNamespace(returncode=1, stdout=""),
            ]
        )
        windows = Windows({"XDG_CURRENT_DESKTOP": "Hyprland"}, run=lambda *a, **k: next(results))
        self.assertEqual(windows.poll(), {"class": "code", "title": "main.py"})
        self.assertEqual(windows.poll(), {})
        self.assertIsNotNone(windows.error)

    def test_other_desktops_are_explicitly_unsupported(self):
        for desktop in ("GNOME", "KDE", "sway", "X11"):
            windows = Windows(
                {"DISPLAY": ":1", "XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": desktop}
            )
            self.assertEqual(windows.poll(), {})
            self.assertIn("not supported yet", windows.error)

    def test_window_backend_extension(self):
        windows = Windows({}, backend=lambda: {"class": "example", "title": "Future port"})
        self.assertEqual(windows.poll(), {"class": "example", "title": "Future port"})

    def test_socket2_activewindow_fragments_and_unrelated_events(self):
        host, compositor = socket.socketpair()
        host.setblocking(False)
        self.addCleanup(compositor.close)
        windows = Windows({"XDG_CURRENT_DESKTOP": "Hyprland"})
        windows.socket = host
        self.addCleanup(windows.close)
        compositor.sendall(b"activelayout>>mouse,us\nactivewin")
        self.assertFalse(windows.dirty())
        compositor.sendall(b"dow>>chromium,Page title\n")
        self.assertTrue(windows.dirty())
        self.assertFalse(windows.dirty())
