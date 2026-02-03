import argparse
from typing import Any

import pyvisa as visa
import pyvisa.constants as visa_constants

from pyrigol.rigol.dp900 import RigolDP900

MAX_VOLT = 7.0
MIN_VOLT = 3.0
START_VOLT = 5.0
STEP_VOLT = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step all channels together using Enter key presses."
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


def set_all_channels(psu: RigolDP900, voltage: float) -> None:
    for channel in (1, 2, 3):
        psu.set_voltage(channel, voltage)


def discover_resource() -> str | None:
    try:
        resources = visa.ResourceManager()
    except Exception as exc:
        print(f"Warning: NI-VISA is not available ({exc}).")
        return None
    usb_resources = resources.list_resources("USB?*")
    if usb_resources:
        return usb_resources[0]
    print("Warning: No USB VISA resources found. Is the device connected?")
    return None


def next_voltage(current: float, direction: str) -> tuple[float, str]:
    if direction == "down":
        if current <= MIN_VOLT:
            return START_VOLT, "up"
        return round(current - STEP_VOLT, 2), "down"
    if current >= MAX_VOLT:
        return START_VOLT, "down"
    return round(current + STEP_VOLT, 2), "up"


def run_loop(psu: RigolDP900, no_idn: bool) -> None:
    if not no_idn:
        psu.print_info()
    current = START_VOLT
    direction = "down"
    set_all_channels(psu, current)
    print("Press Enter to step voltages. Ctrl+C to exit.")
    while True:
        input()
        current, direction = next_voltage(current, direction)
        set_all_channels(psu, current)
        print(f"Voltage set to {current:.2f} V on all channels.")


def main() -> int:
    args = parse_args()
    resource = args.resource
    if resource is None:
        discovered = discover_resource()
        if discovered is None:
            return 1
        resource = discovered
    psu = RigolDP900(
        resource,
        RigolDP900.loglevel.INFO,
        timeout_ms=args.timeout_ms,
        serial_settings=build_serial_settings(args),
    )
    try:
        run_loop(psu, args.no_idn)
    finally:
        psu.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
