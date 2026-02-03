from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import pyvisa as visa
import pyvisa.constants as visa_constants

from pyrigol.rigol.dp900 import RigolDP900

CH1_MIN = 0.00
CH1_MAX = 32.00
INVERT_LEFT_CUT = 0
INVERT_RIGHT_CUT = 0
MIN_BORDER_LEN = 2
KEY_EXTENDED = b"\xe0"
KEY_UP = b"H"
KEY_DOWN = b"P"
KEY_ENTER = b"\r"
KEY_QUIT = (b"q", b"Q")
ESC_REVERSE = "\x1b[7m"
ESC_RESET = "\x1b[0m"


def _apply_reverse(line: str, enabled: bool) -> str:
    if not enabled:
        return line
    if len(line) < MIN_BORDER_LEN or line[0] != "|" or line[-1] != "|":
        return f"{ESC_REVERSE}{line}{ESC_RESET}"

    inner = line[1:-1]
    left_cut = max(0, min(len(inner), INVERT_LEFT_CUT))
    right_cut = max(0, min(len(inner), INVERT_RIGHT_CUT))
    right_limit = max(left_cut, len(inner) - right_cut)

    left = inner[:left_cut]
    middle = inner[left_cut:right_limit]
    right = inner[right_limit:]
    return f"|{left}{ESC_REVERSE}{middle}{ESC_RESET}{right}|"


def render_channel_box(voltage: float, status: str, is_on: bool) -> str:
    lines = [
        "+--------------------------+",
        _apply_reverse("|           CH1            |", is_on),
        _apply_reverse("|                          |", is_on),
        _apply_reverse(f"|  Voltage: {voltage:>4.2f} V         |", is_on),
        _apply_reverse(f"|  Status : {status:<3}            |", is_on),
        _apply_reverse("|                          |", is_on),
        "+--------------------------+",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive TUI for Rigol DP900 series (CH1 only)."
    )
    parser.add_argument(
        "--resource",
        default=None,
        help="VISA resource string for the power supply.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="VISA timeout in milliseconds.",
    )
    parser.add_argument(
        "--baud-rate",
        type=int,
        default=115200,
        help="Serial baud rate (ASRL only).",
    )
    parser.add_argument(
        "--data-bits",
        type=int,
        default=8,
        choices=[7, 8],
        help="Serial data bits (ASRL only).",
    )
    parser.add_argument(
        "--parity",
        choices=["none", "odd", "even"],
        default="none",
        help="Serial parity (ASRL only).",
    )
    parser.add_argument(
        "--stop-bits",
        choices=["1", "1.5", "2"],
        default="1",
        help="Serial stop bits (ASRL only).",
    )
    parser.add_argument(
        "--read-term",
        default="\n",
        help="Read termination string (ASRL only). Use empty for None.",
    )
    parser.add_argument(
        "--write-term",
        default="\n",
        help="Write termination string (ASRL only). Use empty for None.",
    )
    parser.add_argument(
        "--no-idn",
        action="store_true",
        help="Skip the *IDN? query.",
    )
    return parser.parse_args()


def discover_resource() -> str | None:
    try:
        resources = visa.ResourceManager()
    except Exception as exc:
        print(
            f"Warning: NI-VISA is not available ({exc}). "
            "Download: https://www.ni.com/en/support/downloads/drivers/"
            "download.ni-visa.html#585834",
            file=sys.stderr,
        )
        return None

    usb_resources = resources.list_resources("USB?*")
    if usb_resources:
        return usb_resources[0]

    all_resources = resources.list_resources()
    if all_resources:
        return all_resources[0]

    print(
        "Warning: No VISA resources found. Is the device connected?",
        file=sys.stderr,
    )
    return None


def build_serial_settings(args: argparse.Namespace) -> dict[str, Any]:
    parity_map = {
        "none": visa_constants.Parity.none,
        "odd": visa_constants.Parity.odd,
        "even": visa_constants.Parity.even,
    }
    stop_bits_map = {
        "1": visa_constants.StopBits.one,
        "1.5": visa_constants.StopBits.one_and_a_half,
        "2": visa_constants.StopBits.two,
    }
    read_term = None if args.read_term == "" else args.read_term
    write_term = None if args.write_term == "" else args.write_term
    return {
        "baud_rate": args.baud_rate,
        "data_bits": args.data_bits,
        "parity": parity_map[args.parity],
        "stop_bits": stop_bits_map[args.stop_bits],
        "read_termination": read_term,
        "write_termination": write_term,
    }


def draw_screen(voltage: float, status: str, is_on: bool) -> None:
    os.system("cls")
    print(render_channel_box(voltage, status, is_on))
    print("")
    print("Use Up/Down arrows to adjust by 0.25 V. Enter toggles on/off.")
    print("Press Q to quit.")


def clamp_voltage(voltage: float) -> float:
    return max(CH1_MIN, min(CH1_MAX, voltage))


def run_tui_loop(psu: RigolDP900, voltage: float, is_on: bool) -> None:
    import msvcrt  # Windows-only

    status = "ON" if is_on else "OFF"
    psu.set_voltage(1, voltage)

    while True:
        draw_screen(voltage, status, is_on)
        key = msvcrt.getch()
        if key in KEY_QUIT:
            break
        if key == KEY_ENTER:
            is_on = not is_on
            status = "ON" if is_on else "OFF"
            psu.output_state(1, 1 if is_on else 0)
            continue
        if key != KEY_EXTENDED:
            time.sleep(0.02)
            continue

        key = msvcrt.getch()
        if key == KEY_UP:
            voltage = clamp_voltage(voltage + 0.25)
            psu.set_voltage(1, voltage)
        elif key == KEY_DOWN:
            voltage = clamp_voltage(voltage - 0.25)
            psu.set_voltage(1, voltage)
        time.sleep(0.02)


def main() -> int:
    args = parse_args()
    voltage = 5.00
    is_on = False

    if sys.platform != "win32":
        print("This TUI input loop currently supports Windows only.")
        print(render_channel_box(voltage, "OFF", is_on))
        return 1

    resource = args.resource or discover_resource()
    if resource is None:
        return 1

    serial_settings = build_serial_settings(args)
    psu = RigolDP900(
        resource,
        RigolDP900.loglevel.INFO,
        timeout_ms=args.timeout_ms,
        serial_settings=serial_settings,
    )
    try:
        if not args.no_idn:
            psu.print_info()
        run_tui_loop(psu, voltage, is_on)
    finally:
        psu.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
