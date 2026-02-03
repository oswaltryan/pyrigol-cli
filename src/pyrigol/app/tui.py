from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import pyvisa as visa
import pyvisa.constants as visa_constants

from pyrigol.rigol.dp900 import RigolDP900

CH1_MIN = 0.00
CH1_MAX = 32.00
INVERT_LEFT_CUT = 0
INVERT_RIGHT_CUT = 0
INNER_WIDTH = 26
MAX_INT_DIGITS = 2
MAX_FRAC_DIGITS = 2
MIN_BORDER_LEN = 2
KEY_EXTENDED = b"\xe0"
KEY_UP = b"H"
KEY_DOWN = b"P"
KEY_TOGGLE = b" "
KEY_CONFIRM = b"\r"
KEY_DOT = b"."
DOT_CHAR = "."
DOT_SPLIT_MAX = 1
KEY_BACKSPACE = (b"\x08", b"\x7f")
KEY_QUIT = (b"q", b"Q")
ESC_REVERSE = "\x1b[7m"
ESC_RESET = "\x1b[0m"
DIGIT_KEYS = tuple(str(d).encode() for d in range(10))


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


def _format_inner(text: str, width: int) -> str:
    return text.ljust(width)[:width]


def render_channel_box(
    channel_label: str, voltage: float, status: str, is_selected: bool
) -> str:
    voltage_text = f"  Voltage: {voltage:>5.2f} V"
    status_text = f"  Status : {status:<3}"
    header_text = f"           {channel_label}            "
    lines = [
        "+--------------------------+",
        _apply_reverse(f"|{_format_inner(header_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner('', INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner(voltage_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner(status_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner('', INNER_WIDTH)}|", is_selected),
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


def draw_screen(
    channel_label: str, voltage: float, status: str, is_selected: bool
) -> None:
    os.system("cls")
    print(render_channel_box(channel_label, voltage, status, is_selected))
    print("")
    print("Use Up/Down arrows to adjust by 0.25 V. Space toggles on/off.")
    print("Type 0-9 and optional '.' to set voltage. Enter confirms.")
    print("Press Q to quit.")


def clamp_voltage(voltage: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, voltage))


@dataclass(frozen=True)
class ChannelContext:
    psu: RigolDP900
    selected_channel: int
    min_v: float
    max_v: float


@dataclass
class UiState:
    voltage: float
    is_on: bool
    status: str
    input_buffer: str


def apply_voltage(ctx: ChannelContext, value: float) -> None:
    ctx.psu.set_voltage(ctx.selected_channel, value)


def try_apply_candidate(
    candidate: str,
    current_voltage: float,
    ctx: ChannelContext,
) -> tuple[str, float, bool]:
    try:
        candidate_value = float(candidate)
    except ValueError:
        return "", current_voltage, False

    if not (ctx.min_v <= candidate_value <= ctx.max_v):
        return "", current_voltage, False

    apply_voltage(ctx, candidate_value)
    return candidate, candidate_value, True


def can_append_digit(input_buffer: str) -> bool:
    if DOT_CHAR in input_buffer:
        parts = input_buffer.split(DOT_CHAR, DOT_SPLIT_MAX)
        return len(parts[1]) < MAX_FRAC_DIGITS
    return len(input_buffer) < MAX_INT_DIGITS


def try_build_candidate(input_buffer: str, key: bytes) -> str | None:
    if key in DIGIT_KEYS:
        if not can_append_digit(input_buffer):
            return None
        return input_buffer + key.decode()
    if key == KEY_DOT:
        if DOT_CHAR in input_buffer or len(input_buffer) == 0:
            return None
        return input_buffer + DOT_CHAR
    return None


def handle_backspace(ctx: ChannelContext, state: UiState) -> UiState:
    if not state.input_buffer:
        return state

    updated = state.input_buffer[:-1]
    if not updated:
        return UiState(state.voltage, state.is_on, state.status, updated)

    buffer_value, voltage, applied = try_apply_candidate(updated, state.voltage, ctx)
    if applied:
        return UiState(voltage, state.is_on, state.status, buffer_value)

    return UiState(state.voltage, state.is_on, state.status, updated)


def handle_numeric_input(
    key: bytes,
    state: UiState,
    ctx: ChannelContext,
) -> tuple[UiState, bool]:
    candidate = try_build_candidate(state.input_buffer, key)
    if candidate is None:
        return state, False

    buffer_value, voltage, applied = try_apply_candidate(candidate, state.voltage, ctx)
    if not applied:
        return state, False

    return UiState(voltage, state.is_on, state.status, buffer_value), True


def handle_adjustment_key(
    key: bytes,
    state: UiState,
    ctx: ChannelContext,
) -> tuple[UiState, bool]:
    if key == KEY_UP:
        voltage = clamp_voltage(state.voltage + 0.25, ctx.min_v, ctx.max_v)
        apply_voltage(ctx, voltage)
        return UiState(voltage, state.is_on, state.status, ""), True
    if key == KEY_DOWN:
        voltage = clamp_voltage(state.voltage - 0.25, ctx.min_v, ctx.max_v)
        apply_voltage(ctx, voltage)
        return UiState(voltage, state.is_on, state.status, ""), True
    return state, False


def handle_toggle(state: UiState, ctx: ChannelContext) -> UiState:
    is_on = not state.is_on
    status = "ON" if is_on else "OFF"
    ctx.psu.output_state(ctx.selected_channel, 1 if is_on else 0)
    return UiState(state.voltage, is_on, status, state.input_buffer)


def handle_confirm(state: UiState) -> UiState:
    return UiState(state.voltage, state.is_on, state.status, "")


def handle_extended_key(key: bytes, state: UiState, ctx: ChannelContext) -> UiState:
    updated, _ = handle_adjustment_key(key, state, ctx)
    return updated


def handle_key(
    key: bytes, state: UiState, ctx: ChannelContext, msvcrt: Any
) -> tuple[UiState, bool]:
    if key in KEY_QUIT:
        return state, True
    if key == KEY_TOGGLE:
        return handle_toggle(state, ctx), False
    if key in KEY_BACKSPACE:
        return handle_backspace(ctx, state), False
    if key == KEY_CONFIRM:
        return handle_confirm(state), False
    if key != KEY_EXTENDED:
        updated, _ = handle_numeric_input(key, state, ctx)
        return updated, False

    next_key = msvcrt.getch()
    return handle_extended_key(next_key, state, ctx), False


def run_tui_loop(psu: RigolDP900, voltage: float, is_on: bool) -> None:
    import msvcrt  # Windows-only

    channel_limits = {1: (CH1_MIN, CH1_MAX)}
    selected_channel = 1
    channel_label = "CH1"
    min_v, max_v = channel_limits[selected_channel]
    ctx = ChannelContext(psu, selected_channel, min_v, max_v)
    state = UiState(voltage, is_on, "ON" if is_on else "OFF", "")
    apply_voltage(ctx, voltage)

    while True:
        is_selected = selected_channel == 1
        draw_screen(channel_label, state.voltage, state.status, is_selected)
        key = msvcrt.getch()
        state, should_quit = handle_key(key, state, ctx, msvcrt)
        if should_quit:
            break
        time.sleep(0.02)


def main() -> int:
    args = parse_args()
    voltage = 5.00
    is_on = False

    if sys.platform != "win32":
        print("This TUI input loop currently supports Windows only.")
        print(render_channel_box("CH1", voltage, "OFF", True))
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
