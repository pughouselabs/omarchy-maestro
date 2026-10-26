"""bin/maestro-settings: one window, focus on relaunch, update notice, never a kill."""

import isolation  # noqa: F401, I001

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin/maestro-settings"
_loader = importlib.machinery.SourceFileLoader("maestro_settings_launcher", str(LAUNCHER))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
launcher = importlib.util.module_from_spec(_spec)
_loader.exec_module(launcher)

# Stand-ins on PATH. Each call is logged as a JSON argv line. `qs ... ipc call
# maestro focus` succeeds only when FAKE_QS_WINDOW=1. Starting the app exits at
# once, or with FAKE_QS_STAY=1 stays up like a real window (same PID as the launcher).
FAKE_QS = f"""#!{sys.executable}
import json, os, sys, time
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["qs"] + sys.argv[1:]) + "\\n")
if "ipc" in sys.argv:
    sys.exit(0 if os.environ.get("FAKE_QS_WINDOW") == "1" else 1)
if os.environ.get("FAKE_QS_STAY") == "1":
    time.sleep(60)
"""
FAKE_NOTIFY = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["notify-send"] + sys.argv[1:]) + "\\n")
"""
FOCUS = ["ipc", "call", "maestro", "focus"]
NOTICE = [
    "notify-send",
    "--app-name=Maestro",
    "Maestro was updated",
    "Close and reopen it to use the new version.",
]


def tree(root):
    app = Path(root) / "app"
    (app / "assets").mkdir(parents=True)
    (app / "shell.qml").write_text("ShellRoot {}\n")
    (app / "assets/icon.svg").write_text("<svg/>\n")
    return app


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"])
        self.app = tree(self.root)

    def test_stable_when_nothing_changes(self):
        self.assertEqual(launcher.fingerprint(self.app), launcher.fingerprint(self.app))

    def test_edits_additions_and_removals_change_it(self):
        before = launcher.fingerprint(self.app)
        (self.app / "shell.qml").write_text("ShellRoot { id: changed }\n")
        edited = launcher.fingerprint(self.app)
        (self.app / "assets/new.svg").write_text("<svg/>\n")
        added = launcher.fingerprint(self.app)
        (self.app / "assets/new.svg").unlink()
        self.assertEqual(len({before, edited, added}), 3)
        self.assertEqual(launcher.fingerprint(self.app), edited)

    def test_hashes_contents_not_size_or_time(self):
        before = launcher.fingerprint(self.app)
        os.utime(self.app / "shell.qml", (1, 1))
        self.assertEqual(launcher.fingerprint(self.app), before)
        (self.app / "shell.qml").write_text("ShellRoot {}\r")  # same size, new bytes
        os.utime(self.app / "shell.qml", (1, 1))
        self.assertNotEqual(launcher.fingerprint(self.app), before)

    def test_renaming_a_file_changes_it(self):
        before = launcher.fingerprint(self.app)
        (self.app / "assets/icon.svg").rename(self.app / "assets/logo.svg")
        self.assertNotEqual(launcher.fingerprint(self.app), before)

    def test_large_files_are_read_in_chunks(self):
        image = self.app / "assets/render.png"
        image.write_bytes(b"\x89PNG" + b"\0" * (3 * launcher.CHUNK))
        before = launcher.fingerprint(self.app)
        with open(image, "r+b") as handle:
            handle.seek(2 * launcher.CHUNK + 5)
            handle.write(b"\1")
        self.assertNotEqual(launcher.fingerprint(self.app), before)

    def test_follows_symlinked_directories(self):
        outside = Path(self.root) / "outside"
        outside.mkdir()
        (outside / "Shared.qml").write_text("Item {}\n")
        (self.app / "shared").symlink_to(outside, target_is_directory=True)
        before = launcher.fingerprint(self.app)
        (outside / "Shared.qml").write_text("Item { id: changed }\n")
        self.assertNotEqual(launcher.fingerprint(self.app), before)

    def test_symlink_loops_and_broken_links_end(self):
        (self.app / "assets/loop").symlink_to(self.app, target_is_directory=True)
        (self.app / "broken").symlink_to(Path(self.root) / "missing")
        self.assertEqual(len(launcher.fingerprint(self.app)), 64)

    def test_caches_and_dotfiles_are_ignored(self):
        before = launcher.fingerprint(self.app)
        (self.app / "__pycache__").mkdir()
        (self.app / "__pycache__/x.pyc").write_text("x")
        (self.app / ".shell.qml.swp").write_text("x")
        self.assertEqual(launcher.fingerprint(self.app), before)

    def test_ignores_the_clock(self):
        before = launcher.fingerprint(self.app)
        with (
            mock.patch("time.time", return_value=0.0),
            mock.patch("time.monotonic", return_value=1e9),
        ):
            self.assertEqual(launcher.fingerprint(self.app), before)
        source = LAUNCHER.read_text()
        for clock in ("time.time", "clock_gettime", "btime", "st_mtime", "st_size"):
            self.assertNotIn(clock, source)


class LaunchTests(unittest.TestCase):
    """Runs a copy of the launcher next to a temporary app, with fake tools."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"]))
        self.app = tree(self.root)
        (self.root / "bin").mkdir()
        self.script = self.root / "bin/maestro-settings"
        shutil.copy(LAUNCHER, self.script)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.log = self.root / "calls.log"
        self.path = self.runtime / "maestro-settings.fingerprint"

    def tool(self, name, source):
        path = self.tools / name
        path.write_text(source)
        path.chmod(0o755)

    def env(self, window=False, **extra):
        base = {
            "PATH": str(self.tools),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "XDG_STATE_HOME": str(self.root / "state"),
            "HOME": str(self.root),
            "FAKE_LOG": str(self.log),
            "FAKE_QS_WINDOW": "1" if window else "0",
        }
        base.update(extra)
        return {key: value for key, value in base.items() if value is not None}

    def launch(self, window=False, **extra):
        return subprocess.run(
            [sys.executable, "-I", str(self.script)],
            env=self.env(window, **extra),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def start_window(self):
        """The first launch, left running as the window (the fake qs keeps its PID)."""
        child = subprocess.Popen(
            [sys.executable, "-I", str(self.script)],
            env=self.env(FAKE_QS_STAY="1"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)  # the test's own child; the launcher never signals
        deadline = time.monotonic() + 10
        while ["qs", "--no-duplicate", "-p", str(self.app)] not in self.calls():
            self.assertLess(time.monotonic(), deadline, "the fake window never started")
            time.sleep(0.02)
        self.log.unlink()
        return child

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def stamp(self):
        return json.loads(self.path.read_text())

    def change_app(self, text="updated"):
        (self.app / "shell.qml").write_text(f"ShellRoot {{ id: {text} }}\n")

    def test_first_launch_stamps_the_window_it_starts(self):
        self.tool("qs", FAKE_QS)
        window = self.start_window()
        stamp = self.stamp()
        self.assertEqual(stamp["pid"], window.pid)
        self.assertEqual(stamp["start"], launcher.start_ticks(window.pid))
        self.assertEqual(stamp["fingerprint"], launcher.fingerprint(self.app))

    def test_running_current_window_is_only_focused(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        self.start_window()
        result = self.launch(window=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["qs", "-p", str(self.app), *FOCUS]])

    def test_updated_app_focuses_and_notifies_without_closing(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        window = self.start_window()
        self.change_app()
        result = self.launch(window=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["qs", "-p", str(self.app), *FOCUS], NOTICE])
        self.assertIsNone(window.poll())

    def test_notice_shows_once_per_update(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        self.start_window()
        self.change_app("first")
        for _ in range(3):
            self.launch(window=True)
        self.assertEqual([call[0] for call in self.calls()].count("notify-send"), 1)
        self.assertEqual(self.stamp()["notified"], launcher.fingerprint(self.app))
        self.change_app("second")
        self.launch(window=True)
        self.launch(window=True)
        self.assertEqual([call[0] for call in self.calls()].count("notify-send"), 2)

    def test_stamp_of_an_exited_window_is_ignored(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        self.assertEqual(self.launch().returncode, 0)  # its fake window exits at once
        self.change_app()
        self.log.unlink()
        result = self.launch(window=True)  # a window started some other way is running
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [["qs", "-p", str(self.app), *FOCUS]])

    def test_stamp_with_a_reused_pid_is_ignored(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        alive = subprocess.Popen(["sleep", "30"])
        self.addCleanup(alive.wait)
        self.addCleanup(alive.kill)
        ticks = launcher.start_ticks(alive.pid)
        self.path.write_text(json.dumps({"pid": alive.pid, "start": ticks + 1, "fingerprint": "x"}))
        result = self.launch(window=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(NOTICE, self.calls())

    def test_unreadable_stamp_is_ignored(self):
        self.tool("qs", FAKE_QS)
        self.tool("notify-send", FAKE_NOTIFY)
        self.path.write_text("an older version\n")
        result = self.launch(window=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.calls(), [["qs", "-p", str(self.app), *FOCUS]])

    def test_missing_notify_send_is_skipped_quietly(self):
        self.tool("qs", FAKE_QS)
        self.start_window()
        self.change_app()
        result = self.launch(window=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_missing_qs_is_one_clear_line(self):
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "Maestro: Quickshell (qs) was not found on PATH.\n")

    def test_missing_runtime_variable_is_one_clear_line(self):
        self.tool("qs", FAKE_QS)
        result = self.launch(XDG_RUNTIME_DIR=None)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_runtime_folder_is_one_clear_line(self):
        self.tool("qs", FAKE_QS)
        result = self.launch(XDG_RUNTIME_DIR=str(self.root / "gone"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertIn("runtime folder", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class NeverSignalsTests(unittest.TestCase):
    """Runs main() in process with every way of ending a process trapped."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=os.environ["XDG_STATE_HOME"]))
        self.app = tree(self.root)
        runtime = self.root / "runtime"
        runtime.mkdir(mode=0o700)
        # A stamp owned by a live process (this test) for an older version of the app.
        stamp = {"pid": os.getpid(), "start": launcher.start_ticks(os.getpid()), "fingerprint": "x"}
        (runtime / "maestro-settings.fingerprint").write_text(json.dumps(stamp))
        self.commands = []
        self.window = True
        forbidden = mock.Mock(side_effect=AssertionError("the launcher sent a signal"))
        patches = [
            mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}),
            mock.patch.object(launcher, "APP", str(self.app)),
            mock.patch.object(launcher.shutil, "which", return_value="/usr/bin/tool"),
            mock.patch.object(launcher.subprocess, "run", side_effect=self.run_command),
            mock.patch.object(launcher.os, "execvp", side_effect=SystemExit(0)),
            mock.patch.object(launcher.time, "sleep"),
            mock.patch.object(launcher.os, "kill", forbidden),
            mock.patch.object(launcher.os, "killpg", forbidden),
            mock.patch("signal.pthread_kill", forbidden),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.forbidden = forbidden

    def run_command(self, argv, **_kwargs):
        self.commands.append(list(argv))
        focus = argv[:1] == ["qs"] and "ipc" in argv
        return subprocess.CompletedProcess(argv, 0 if (self.window or not focus) else 1)

    def test_stale_window_is_focused_and_never_killed(self):
        self.assertEqual(launcher.main(), 0)
        self.forbidden.assert_not_called()
        self.assertFalse(any("kill" in argv for argv in self.commands), self.commands)
        self.assertEqual(self.commands[-1][0], "/usr/bin/tool")

    def test_start_path_never_kills(self):
        self.window = False
        with self.assertRaises(SystemExit):
            launcher.main()
        self.forbidden.assert_not_called()
        self.assertFalse(any("kill" in argv for argv in self.commands), self.commands)

    def test_source_has_no_kill_paths(self):
        source = LAUNCHER.read_text()
        for word in ("pkill", "killall", "os.kill", "SIGTERM", '"kill"', "import signal"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()


class ConcurrentNoticeTests(unittest.TestCase):
    def test_simultaneous_launches_send_one_notice(self):
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp, "app")
            app.mkdir()
            (app / "a.qml").write_text("old")
            stamp = Path(tmp, "maestro-settings.fingerprint")
            launcher.save(
                str(stamp), {"pid": 1, "start": 1, "fingerprint": launcher.fingerprint(str(app))}
            )
            (app / "a.qml").write_text("new")
            sent = []

            def slow_notice():
                time.sleep(0.05)  # widen the race window
                sent.append(1)

            with (
                mock.patch.object(launcher, "owns", return_value=True),
                mock.patch.object(launcher, "notify_updated", side_effect=slow_notice),
            ):
                threads = [
                    threading.Thread(target=launcher.check_for_update, args=(str(stamp), str(app)))
                    for _ in range(6)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            self.assertEqual(len(sent), 1)
