import argparse
import sys
from typing import Any

import pyvisa as visa
import pyvisa.constants as visa_constants

from pyrigol.rigol.dp900 import RigolDP900


def list_resources() -> None:
    try:
        resources = visa.ResourceManager()
    except Exception as exc:
        print(
            f"Warning: NI-VISA is not available ({exc}). "
            "Download: https://www.ni.com/en/support/downloads/drivers/"
            "download.ni-visa.html#585834",
            file=sys.stderr,
        )
        return
    usb_resources = resources.list_resources("USB?*")
    if usb_resources:
        for resource in usb_resources:
            print(resource)
        return
    print(
        "Warning: No USB VISA resources found. Is the device connected?",
        file=sys.stderr,
    )
    for resource in resources.list_resources():
        print(resource)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set DP900 channel voltages over USB (PyVISA).")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available VISA resources and exit.",
    )
    parser.add_argument(
        "--resource",
        default="USB0::0x1AB1::0x0E11::DP9XXXXXXXX::INSTR",
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
    parser.add_argument("--ch1", type=float, default=1.0, help="CH1 voltage (V).")
    parser.add_argument("--ch2", type=float, default=1.0, help="CH2 voltage (V).")
    parser.add_argument("--ch3", type=float, default=1.0, help="CH3 voltage (V).")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output-on",
        nargs="?",
        const="all",
        choices=["all", "1", "2", "3"],
        help="Turn outputs on after setting voltages. "
        "Use no value for all channels or 1/2/3 for a single channel.",
    )
    output_group.add_argument(
        "--output-off",
        nargs="?",
        const="all",
        choices=["all", "1", "2", "3"],
        help="Turn outputs off after setting voltages. "
        "Use no value for all channels or 1/2/3 for a single channel.",
    )
    output_group.add_argument(
        "--output-status",
        nargs="?",
        const="all",
        choices=["all", "1", "2", "3"],
        help="Query output state and exit. "
        "Use no value for all channels or 1/2/3 for a single channel.",
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


def channels_from_option(option: str) -> list[int]:
    if option == "all":
        return [1, 2, 3]
    return [int(option)]


def print_output_status(psu: RigolDP900, option: str) -> None:
    for channel in channels_from_option(option):
        is_on = psu.get_output_state(channel)
        status = "ON" if is_on else "OFF"
        print(f"CH{channel}: {status}")


def apply_output_state(psu: RigolDP900, option: str, state: int) -> None:
    for channel in channels_from_option(option):
        psu.output_state(channel, state)


def main() -> int:
    args = parse_args()
    if args.list:
        list_resources()
        return 0
    serial_settings = build_serial_settings(args)
    psu = RigolDP900(
        args.resource,
        RigolDP900.loglevel.INFO,
        timeout_ms=args.timeout_ms,
        serial_settings=serial_settings,
    )
    try:
        if not args.no_idn:
            psu.print_info()
        if args.output_status is not None:
            print_output_status(psu, args.output_status)
            return 0
        psu.set_voltage(1, args.ch1)
        psu.set_voltage(2, args.ch2)
        psu.set_voltage(3, args.ch3)

        if args.output_on is not None:
            apply_output_state(psu, args.output_on, 1)
        if args.output_off is not None:
            apply_output_state(psu, args.output_off, 0)
    finally:
        psu.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
