"""tools/exitKissMode.py: telling which TNC answered the KISS exit."""

import importlib.util
import unittest

from pathlib import Path

import fakes  # noqa: F401  (puts the repo root on sys.path)

ROOT = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "exitKissMode", ROOT / "tools" / "exitKissMode.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()

# Verbatim from Dave's OpenTNC (2026-10-30), leaving KISS: the sign-on
# banner, with no "cmd:" or "kam" in it -- which the script used to
# report as "No recognizable response".
OPENTNC_BANNER = (
    b"AE6EO OpenTNC 7.2, built from git version 461d426\r\n"
    b"Board target rpi_pico/rp2040, clock speed 125000000\r\n"
    b"Firmware Copyright (c) 2022-2026, David C Platt\r\n"
    b"Licensed for use under the GNU General Public License, Version 3\r\n"
    b"Running on Zephyr OS, version v4.5.0-817-g25206336e4fa\r\n"
)


class RecognizeTests(unittest.TestCase):
    def test_opentnc_banner(self):
        self.assertEqual(tool.recognize(OPENTNC_BANNER), "OpenTNC")

    def test_opentnc_any_firmware_version(self):
        # Keyed on the model name, not "7.2".
        banner = OPENTNC_BANNER.replace(b"7.2", b"8.0")
        self.assertEqual(tool.recognize(banner), "OpenTNC")

    def test_kam_xl_banner(self):
        self.assertEqual(tool.recognize(b"[KAM-XL-1.0-HM$]\r\ncmd:"), "KAM-XL")

    def test_bare_prompt(self):
        self.assertEqual(tool.recognize(b"\r\ncmd:"), "TNC")

    def test_nothing(self):
        self.assertIsNone(tool.recognize(b""))
        self.assertIsNone(tool.recognize(b"\xc0\x00garbage\xc0"))


# Verbatim from Dave's OpenTNC (2026-11-19), already at cmd: (the daemon
# had left KISS when it stopped): the exit bytes come straight back as
# an echo, and the probe's CR submits them as a command.
ECHO = b"\xc0\xff\xc0"
OPENTNC_REJECT = (
    b"\r\nUnknown command: \xc0\xff\xc0\r\n"
    b"Type 'help' to list all commands\r\ncmd:"
)


class AssessTests(unittest.TestCase):
    def test_opentnc_already_at_cmd(self):
        self.assertEqual(tool.assess(ECHO, OPENTNC_REJECT), ("OpenTNC", False))

    def test_opentnc_left_kiss(self):
        self.assertEqual(tool.assess(OPENTNC_BANNER, b"\r\ncmd:"),
                         ("OpenTNC", True))

    def test_kam_xl_left_kiss(self):
        self.assertEqual(tool.assess(b"[KAM-XL-1.0-HM$]\r\ncmd:", b"cmd:"),
                         ("KAM-XL", True))

    def test_echo_and_bare_prompt(self):
        self.assertEqual(tool.assess(ECHO, b"\r\ncmd:"), ("TNC", False))

    def test_opentnc_left_kiss_with_only_prompts(self):
        # Verbatim from Dave's OpenTNC (2026-11-19): leaving KISS it
        # answered with prompts only -- no banner, no echo.
        reply = b"\\\r\n\rcmd:\r\n\r\n\rcmd:"
        self.assertEqual(tool.assess(reply, b"\r\ncmd:"), ("TNC", True))

    def test_still_stuck(self):
        self.assertEqual(tool.assess(b"", b""), (None, True))

    def test_opentnc_reject_line_alone_is_recognized(self):
        self.assertEqual(tool.recognize(OPENTNC_REJECT), "OpenTNC")


if __name__ == "__main__":
    unittest.main()
