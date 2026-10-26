"""One thread owns every virtual input event and all held input state."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque

LOG = logging.getLogger("maestrod")


class InputOwner:
    """Serialize complete chords and retry releases before any new input press."""

    def __init__(self, output, request_timeout=2):
        self.output = output
        self.request_timeout = request_timeout
        self._queue = queue.Queue()
        self._held = {}
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="maestro-input", daemon=True)
        self._thread.start()

    def _submit(self, op, *args):
        if self._closed:
            raise RuntimeError("virtual input is closed")
        task = {
            "op": op,
            "args": args,
            "done": threading.Event(),
            "result": None,
            "lock": threading.Lock(),
            "started": False,
            "cancelled": False,
        }
        self._queue.put(task)
        if not task["done"].wait(self.request_timeout):
            with task["lock"]:
                if not task["started"]:
                    task["cancelled"] = True
                    raise TimeoutError("virtual input owner did not respond")
            # Once an emitter has started, wait for its result. A timed-out
            # press must never be allowed to finish after its caller returns.
            task["done"].wait()
        if isinstance(task["result"], BaseException):
            raise task["result"]
        return task["result"]

    def press(self, codes, owner, cancel=None):
        token = object()
        self._submit("press", token, codes, owner, cancel)
        return token

    def release(self, token):
        return self._submit("release", token)

    def chord(self, codes, owner, cancel=None):
        return self._submit("chord", codes, owner, cancel)

    def scroll(self, direction, modifier=None):
        return self._submit("scroll", direction, modifier)

    def cancel(self, owner=None):
        return self._submit("cancel", owner)

    def close(self):
        if self._closed:
            return
        try:
            self.cancel()
            self._submit("stop")
            self._thread.join(timeout=1)
        except Exception:
            LOG.exception("input owner shutdown failed; destroying virtual input device")
            self.output.close()
        finally:
            self._closed = True

    def _run(self):
        deferred = deque()
        while True:
            if any(entry["pending"] for entry in self._held.values()):
                try:
                    task = self._queue.get(timeout=0.02)
                except queue.Empty:
                    self._retry_pending()
                    continue
                if task["op"] in ("press", "chord", "scroll"):
                    deferred.append(task)
                    self._retry_pending()
                    continue
            elif deferred:
                task = deferred.popleft()
            else:
                task = self._queue.get()
            with task["lock"]:
                if task["cancelled"]:
                    task["done"].set()
                    continue
                task["started"] = True
            op, args = task["op"], task["args"]
            try:
                value = getattr(self, f"_do_{op}")(*args)
            except BaseException as exc:
                value = exc
            task["result"] = value
            task["done"].set()
            if op == "stop":
                break

    def _do_press(self, token, codes, owner, cancel):
        if cancel is not None and cancel.is_set():
            return False
        entry = {"owner": owner, "codes": [], "pending": False}
        self._held[token] = entry
        try:
            for code in codes:
                # The emitter may send the event before raising. Record it first.
                entry["codes"].append(code)
                self.output.press(code)
        except BaseException:
            self._do_release(token)
            raise
        return True

    def _do_release(self, token):
        entry = self._held.get(token)
        if entry is None:
            return True
        entry["pending"] = True
        for code in list(reversed(entry["codes"])):
            for attempt in range(2):
                try:
                    self.output.release(code)
                    entry["codes"].remove(code)
                    break
                except Exception as exc:
                    LOG.warning(
                        "input release failed for %s (attempt %s): %s", code, attempt + 1, exc
                    )
        if not entry["codes"]:
            self._held.pop(token, None)
            return True
        return False

    def _do_chord(self, codes, owner, cancel):
        token = object()
        if not self._do_press(token, codes, owner, cancel):
            return True
        return self._do_release(token)

    def _do_scroll(self, direction, modifier):
        if modifier is None:
            self.output.scroll(direction)
            return True
        token = object()
        self._do_press(token, [modifier], None, None)
        try:
            self.output.scroll(direction)
        finally:
            self._do_release(token)
        return True

    def _do_cancel(self, owner):
        for token, entry in list(self._held.items()):
            if owner is None or entry["owner"] == owner:
                self._do_release(token)
        return True

    def _retry_pending(self):
        for token, entry in list(self._held.items()):
            if entry["pending"]:
                self._do_release(token)

    def _do_stop(self):
        deadline = time.monotonic() + 0.2
        while self._held and time.monotonic() < deadline:
            for token in list(self._held):
                self._do_release(token)
            if self._held:
                time.sleep(0.02)
        if self._held:
            remaining = [code for entry in self._held.values() for code in entry["codes"]]
            LOG.error("destroying virtual input device with unreleased codes: %s", remaining)
        try:
            self.output.close()
        finally:
            self._held.clear()
        return True
