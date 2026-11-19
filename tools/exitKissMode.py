"""
One-off diagnostic/recovery script: sends the standard KISS exit
sequence directly over the serial port, bypassing kamxl.py's normal
Terminal Mode protocol entirely (which won't get a response at all
if the TNC is actually in KISS mode -- that's the point of this
script).

Per the KAM-XL manual ("Exiting KISS mode", ch. "Interface
Communication modes"): send FEND (0xC0), FF (0xFF), FEND (0xC0). The
TNC should reply with its normal Kantronics sign-on banner and drop
back into TERMINAL interface mode for this session.

The OpenTNC takes the same sequence and answers with its own sign-on
banner, e.g. (firmware 7.2):

    AE6EO OpenTNC 7.2, built from git version 461d426
    Board target rpi_pico/rp2040, clock speed 125000000
    ...

so a reply is recognized by the model name ("OpenTNC", "KAM"), never
by a firmware version, or by a cmd: prompt.

A TNC that wasn't in KISS -- usually because the daemon already took
it out when it stopped -- just echoes the three bytes and keeps them
as a command line. So after the exit the script sends a lone CR: a TNC
in KISS ignores it, one at cmd: answers with a prompt (the OpenTNC
first rejects the echoed bytes: "Unknown command: ..."), which also
clears them. The echo tells the two cases apart.

Note that on the KAM-XL this only fixes the *current* session. INTFACE
is a saved parameter that controls what mode the TNC boots into -- if
it's set to KISS, the unit will go straight back into KISS mode on its
next power-cycle/reset unless INTFACE is explicitly set back to
TERMINAL (see the follow-up instructions this script prints if it
works). The OpenTNC's equivalent is a saved KISS ON, which tncstation
no longer uses (it enters with KISS NOW, which isn't saved).

If opening the port fails with "Inappropriate ioctl for device", an
AX.25 KISS daemon (e.g. kissattach, often run as a systemd service)
is likely already attached to it -- stop that first. See
serial_errors.py for the detail; this script surfaces that guidance
automatically rather than showing a raw traceback.

Usage:
    python3 tools/exitKissMode.py /dev/ttyUSB1
"""

import sys
import time

from typing import Optional, Tuple

import serial

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))  # the repo root

from serial_errors import describe_serial_open_failure

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/kamxl"
BAUDRATE = 19200

KISS_EXIT = bytes([0xC0, 0xFF, 0xC0])
PROBE = b"\r"

# Collect the reply until the TNC has been quiet this long, or for at
# most REPLY_MAX seconds: a sign-on banner is several lines, and the
# OpenTNC's cmd: prompt can follow it.
REPLY_QUIET = 1.0
REPLY_MAX = 5.0


def recognize(response: bytes) -> Optional[str]:
    """
    Which TNC answered: "OpenTNC", "KAM-XL", "TNC" (a bare cmd: prompt),
    or None (nothing recognizable). The OpenTNC is recognized by name in
    its sign-on banner, or by its "Type 'help' ..." line after rejecting
    a command -- never by a firmware version.
    """
    text = response.lower()
    if b"opentnc" in text or b"type 'help'" in text:
        return "OpenTNC"
    if b"kam" in text:
        return "KAM-XL"
    if b"cmd:" in text:
        return "TNC"
    return None


def assess(response: bytes, probe: bytes) -> Tuple[Optional[str], bool]:
    """
    (model, was_in_kiss) from the reply to the KISS exit and the reply
    to the CR probe sent after it.

    A TNC that was already at cmd: (the daemon leaves KISS itself when it
    stops) doesn't take C0 FF C0 as a KISS exit: it echoes the bytes back
    and keeps them as a command line, which the probe's CR then submits
    (the OpenTNC: "Unknown command: ...", then cmd:). One that really was
    in KISS answers with its sign-on banner and doesn't echo.
    """
    model = recognize(response) or recognize(probe)
    was_in_kiss = KISS_EXIT not in response
    return model, was_in_kiss


def read_reply(ser: "serial.Serial") -> bytes:
    data = bytearray()
    deadline = time.monotonic() + REPLY_MAX
    quiet_since = time.monotonic()

    while time.monotonic() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            data.extend(chunk)
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= REPLY_QUIET:
            break

    return bytes(data)


def show(label: str, data: bytes) -> None:
    print(f"\n{label} -- raw bytes received ({len(data)}):")
    print(repr(data))
    print("Decoded (best effort):")
    print(data.decode("ascii", errors="replace"))


def main():
    print(f"Opening {PORT} at {BAUDRATE} baud...")

    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.1,
        )
    except Exception as exc:
        print(f"\nCould not open {PORT}:\n")
        print(describe_serial_open_failure(exc))
        sys.exit(1)

    time.sleep(0.1)

    print("Sending KISS exit sequence (FEND, FF, FEND)...")
    ser.reset_input_buffer()
    ser.write(KISS_EXIT)
    ser.flush()
    response = read_reply(ser)

    # A lone CR: ignored by a TNC in KISS mode, answered with a cmd:
    # prompt at command mode -- which also submits (and so clears) any
    # echoed exit bytes left on the command line.
    print("Sending a carriage return to check for a cmd: prompt...")
    ser.write(PROBE)
    ser.flush()
    probe = read_reply(ser)

    ser.close()

    show("KISS exit", response)
    show("CR probe", probe)

    model, was_in_kiss = assess(response, probe)

    if model is None:
        print(
            "\nNo recognizable response. Either it's still stuck, or "
            "it isn't talking at this baud rate -- worth trying a direct "
            "terminal (screen/minicom) session next to see raw behavior."
        )
    elif not was_in_kiss:
        name = "TNC" if model == "TNC" else f"The {model}"
        print(
            f"\n{name} is at its cmd: prompt -- and was already there: it "
            "echoed the exit bytes back, which a TNC in KISS mode doesn't "
            "do (the daemon takes it out of KISS when it stops). Nothing "
            "to do.\nAny \"Unknown command\" above is just those echoed "
            "bytes being rejected; the command line is clear now."
        )
    elif model == "OpenTNC":
        print(
            "\nLooks like it worked -- the OpenTNC left KISS mode and is "
            "back at its cmd: prompt.\n"
            "Nothing to undo for tncstation's own KISS entry (KISS NOW "
            "isn't saved). If it ever starts up in KISS by itself, a "
            "saved KISS ON is left over: type KISS at cmd: to check, and "
            "KISS OFF to clear it."
        )
    elif model == "KAM-XL":
        print(
            "\nLooks like it worked -- the KAM-XL responded with its "
            "sign-on banner / command prompt.\n"
            "IMPORTANT: this only fixes the current session. To "
            "stop it from booting back into KISS mode next time, run "
            "learnKam.py or a quick script that does:\n"
            '    kam.send_command("INTFACE TERMINAL")\n'
            '    kam.send_command("RESET")\n'
            "(or power-cycle it once more after setting INTFACE, per "
            "the manual)."
        )
    else:
        # Only cmd: prompts, nothing naming the TNC (seen from the
        # OpenTNC too: b"\\\r\n\rcmd:\r\n\r\n\rcmd:").
        print(
            "\nLooks like it worked -- the TNC left KISS mode and is back "
            "at its cmd: prompt.\n"
            "OpenTNC: nothing to undo (tncstation enters KISS with KISS "
            "NOW, which isn't saved).\n"
            "KAM-XL: this only fixes the current session; if INTFACE is "
            "saved as KISS it boots back into KISS -- set INTFACE TERMINAL "
            "and RESET (see learnKam.py)."
        )


if __name__ == "__main__":
    main()
