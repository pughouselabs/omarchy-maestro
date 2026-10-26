"""Read-only HID++ feature parsing and diagnostic redaction."""

import json
import unittest

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro import hidpp, mouse


class FeatureDevice:
    def __init__(self, features, replies):
        self.features = set(features)
        self.replies = replies
        self.calls = []

    def has(self, feature):
        return feature in self.features

    def call(self, feature, function, params=b""):
        self.calls.append((feature, function, params))
        reply = self.replies[(feature, function)]
        return reply(params) if callable(reply) else reply


class FeatureTests(unittest.TestCase):
    def test_feature_list_versions(self):
        class Channel:
            def request(self, index, feature_index, function, params=b"", timeout=1):
                if feature_index == 0:
                    return b"\x01\x00\x01"
                if function == 0:
                    return b"\x02"
                return {1: b"\x00\x01\x00\x01", 2: b"\x00\x05\x00\x02"}[params[0]]

        node = hidpp.HidrawNode("fake", 3, 0x046D, 0xC52B, "receiver")
        dev = hidpp.Device(Channel(), 1, node)
        self.assertEqual(
            dev.feature_details(),
            [
                {"id": "0x0000", "version": 0},
                {"id": "0x0001", "version": 1},
                {"id": "0x0005", "version": 2},
            ],
        )

    def test_unified_battery_preferred(self):
        d = FeatureDevice(
            (hidpp.UNIFIED_BATTERY, hidpp.BATTERY_STATUS),
            {
                (hidpp.UNIFIED_BATTERY, 1): bytes((75, 4, 1)),
            },
        )
        self.assertEqual(mouse.battery(d), mouse.Battery(75, "charging", True, "0x1004"))
        self.assertNotIn((hidpp.BATTERY_STATUS, 0, b""), d.calls)

    def test_legacy_battery(self):
        d = FeatureDevice(
            (hidpp.BATTERY_STATUS,),
            {
                (hidpp.BATTERY_STATUS, 0): bytes((50, 45, 0)),
            },
        )
        self.assertEqual(mouse.battery(d), mouse.Battery(50, "discharging", False, "0x1000"))

    def test_extended_dpi_list_read_and_preserving_write(self):
        raw_choices = b"\x01\x90\xe0\x64\x06\x40\x00\x00"  # 400..1600, step 100
        current = [800]
        written = []

        def get_dpi(_):
            return b"\x00" + current[0].to_bytes(2, "big") + b"\x03\xe8\x03\x20\x03\xe8\x02"

        def set_dpi(params):
            written.append(params)
            current[0] = int.from_bytes(params[1:3], "big")
            return b""

        d = FeatureDevice(
            (hidpp.EXTENDED_ADJUSTABLE_DPI,),
            {
                (hidpp.EXTENDED_ADJUSTABLE_DPI, 1): b"\x00\x00\x03",
                (hidpp.EXTENDED_ADJUSTABLE_DPI, 2): b"\x00\x00\x00" + raw_choices,
                (hidpp.EXTENDED_ADJUSTABLE_DPI, 5): get_dpi,
                (hidpp.EXTENDED_ADJUSTABLE_DPI, 6): set_dpi,
            },
        )
        info = mouse.dpi(d)
        self.assertEqual(
            (info.current, info.default, info.minimum, info.maximum, info.step),
            (800, 1000, 400, 1600, 100),
        )
        self.assertEqual((info.y_current, info.y_default, info.lod), (800, 1000, 2))
        self.assertEqual(mouse.set_dpi(d, 1200), 1200)
        self.assertEqual(written, [b"\x00\x04\xb0\x03\x20\x02"])
        self.assertIn((hidpp.EXTENDED_ADJUSTABLE_DPI, 2, b"\x00\x00\x00"), d.calls)

    def test_enhanced_smartshift(self):
        d = FeatureDevice(
            (hidpp.SMART_SHIFT_ENHANCED,),
            {
                (hidpp.SMART_SHIFT_ENHANCED, 1): b"\x02\x14\x32",
            },
        )
        self.assertEqual(mouse.smartshift(d), mouse.SmartShift("ratchet", 20, True))

    def test_thumb_and_hires_wheels(self):
        d = FeatureDevice(
            (hidpp.THUMB_WHEEL, hidpp.HIRES_WHEEL),
            {
                (hidpp.THUMB_WHEEL, 0): b"\x01\x00\x78",
                (hidpp.THUMB_WHEEL, 1): b"\x01\x01",
                (hidpp.HIRES_WHEEL, 1): b"\x07",
            },
        )
        self.assertEqual(mouse.thumb_wheel(d), mouse.ThumbWheel(True, True, 120))
        self.assertEqual(mouse.wheel(d), mouse.Wheel(True, True, True))

    def test_control_flags_and_list(self):
        rows = [
            bytes.fromhex("005000380100010100"),
            bytes.fromhex("0052003a7100030701"),
        ]
        d = FeatureDevice(
            (hidpp.REPROG_CONTROLS_V4,),
            {
                (hidpp.REPROG_CONTROLS_V4, 0): b"\x02",
                (hidpp.REPROG_CONTROLS_V4, 1): lambda params: rows[params[0]],
            },
        )
        result = mouse.controls(d)
        self.assertEqual(result[0], mouse.Control(0x50, 0x38, False, False, False))
        self.assertEqual(result[1], mouse.Control(0x52, 0x3A, True, True, True))
        with self.assertRaises(ValueError):
            mouse.parse_control(b"\x00\x52")

    def test_diagnose_whitelist_excludes_identifiers(self):
        class Device:
            node = hidpp.HidrawNode("/dev/hidraw5", 3, 0x046D, 0xC52B, "receiver")
            index = 1
            wpid = 0x4069
            model = "MX Master 2S"
            version = (4, 5)
            serial = "SECRET-SERIAL"
            unit_id = "SECRET-UNIT"

            def name(self):
                return "Wireless Mouse MX Master 2S SECRET-SERIAL"

            def feature_details(self):
                return [{"id": "0x0003", "version": 2}]

            def has(self, feature):
                return feature == hidpp.BATTERY_STATUS

        report = mouse.diagnose(Device())
        output = json.dumps(report)
        self.assertEqual(report["name"], "MX Master 2S")
        self.assertEqual(report["battery_source"], "0x1000")
        self.assertNotIn("SECRET", output)
        self.assertNotIn("serial", output.lower())
        self.assertNotIn("unit_id", output.lower())
        self.assertIsNone(report["controls"])

        class ReportedName(Device):
            model = None
            wpid = None

        self.assertEqual(mouse.diagnose(ReportedName())["name"], "MX Master 2S")

        class FallbackName(Device):
            model = None
            wpid = None
            reported_name = "Logitech Mouse SECRET-UNIT"

            def name(self):
                raise hidpp.HidppError("name read failed")

        fallback = json.dumps(mouse.diagnose(FallbackName()))
        self.assertIn("unsupported Logitech device", fallback)
        self.assertNotIn("SECRET", fallback)


if __name__ == "__main__":
    unittest.main()
