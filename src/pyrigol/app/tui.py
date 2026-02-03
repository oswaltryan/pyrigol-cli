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
CH2_MIN = 0.00
CH2_MAX = 32.00
CH3_MIN = 0.00
CH3_MAX = 6.00
INVERT_LEFT_CUT = 0
INVERT_RIGHT_CUT = 0
INNER_WIDTH = 26
MAX_INT_DIGITS = 2
MAX_FRAC_DIGITS = 2
MIN_BORDER_LEN = 2
KEY_EXTENDED = b"\xe0"
KEY_UP = b"H"
KEY_DOWN = b"P"
KEY_LEFT = b"K"
KEY_RIGHT = b"M"
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
) -> list[str]:
    voltage_text = f"  Voltage: {voltage:>5.2f} V"
    status_text = f"  Status : {status:<3}"
    header_text = f"           {channel_label}            "
    return [
        "+--------------------------+",
        _apply_reverse(f"|{_format_inner(header_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner('', INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner(voltage_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner(status_text, INNER_WIDTH)}|", is_selected),
        _apply_reverse(f"|{_format_inner('', INNER_WIDTH)}|", is_selected),
        "+--------------------------+",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive TUI for Rigol DP900 series (CH1-CH3)."
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


def draw_screen(boxes: list[list[str]]) -> None:
    os.system("cls")
    for row in zip(*boxes, strict=True):
        print("  ".join(row))
    print("")
    print("Use Up/Down arrows to adjust by 0.25 V. Space toggles on/off.")
    print("Type 0-9 and optional '.' to set voltage. Enter confirms.")
    print("Press Left/Right arrows to select a channel.")
    print("Press Q to quit.")


def clamp_voltage(voltage: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, voltage))


def cycle_channel(
    current: int, channels: dict[int, ChannelState], direction: int
) -> int:
    ordered = sorted(channels)
    if current not in channels:
        return ordered[0]
    idx = ordered.index(current)
    return ordered[(idx + direction) % len(ordered)]


@dataclass(frozen=True)
class ChannelContext:
    psu: RigolDP900
    selected_channel: int
    min_v: float
    max_v: float


@dataclass
class ChannelState:
    voltage: float
    is_on: bool
    status: str
    input_buffer: str


@dataclass
class UiState:
    selected_channel: int
    channels: dict[int, ChannelState]


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


def handle_backspace(ctx: ChannelContext, channel: ChannelState) -> ChannelState:
    if not channel.input_buffer:
        return channel

    updated = channel.input_buffer[:-1]
    if not updated:
        return ChannelState(channel.voltage, channel.is_on, channel.status, updated)

    buffer_value, voltage, applied = try_apply_candidate(updated, channel.voltage, ctx)
    if applied:
        return ChannelState(voltage, channel.is_on, channel.status, buffer_value)

    return ChannelState(channel.voltage, channel.is_on, channel.status, updated)


def handle_numeric_input(
    key: bytes,
    channel: ChannelState,
    ctx: ChannelContext,
) -> tuple[ChannelState, bool]:
    candidate = try_build_candidate(channel.input_buffer, key)
    if candidate is None:
        return channel, False

    buffer_value, voltage, applied = try_apply_candidate(
        candidate, channel.voltage, ctx
    )
    if not applied:
        return channel, False

    return ChannelState(voltage, channel.is_on, channel.status, buffer_value), True


def handle_adjustment_key(
    key: bytes,
    channel: ChannelState,
    ctx: ChannelContext,
) -> tuple[ChannelState, bool]:
    if key == KEY_UP:
        voltage = clamp_voltage(channel.voltage + 0.25, ctx.min_v, ctx.max_v)
        apply_voltage(ctx, voltage)
        return ChannelState(voltage, channel.is_on, channel.status, ""), True
    if key == KEY_DOWN:
        voltage = clamp_voltage(channel.voltage - 0.25, ctx.min_v, ctx.max_v)
        apply_voltage(ctx, voltage)
        return ChannelState(voltage, channel.is_on, channel.status, ""), True
    return channel, False


def handle_toggle(channel: ChannelState, ctx: ChannelContext) -> ChannelState:
    is_on = not channel.is_on
    status = "ON" if is_on else "OFF"
    ctx.psu.output_state(ctx.selected_channel, 1 if is_on else 0)
    return ChannelState(channel.voltage, is_on, status, channel.input_buffer)


def handle_confirm(channel: ChannelState) -> ChannelState:
    return ChannelState(channel.voltage, channel.is_on, channel.status, "")


def handle_extended_key(
    key: bytes, channel: ChannelState, ctx: ChannelContext, state: UiState
) -> tuple[ChannelState, int | None]:
    if key == KEY_LEFT:
        return channel, cycle_channel(state.selected_channel, state.channels, -1)
    if key == KEY_RIGHT:
        return channel, cycle_channel(state.selected_channel, state.channels, 1)
    updated, _ = handle_adjustment_key(key, channel, ctx)
    return updated, None


def handle_key(
    key: bytes, state: UiState, ctx: ChannelContext, msvcrt: Any
) -> tuple[UiState, bool]:
    should_quit = False
    selected = state.channels[state.selected_channel]
    updated = selected
    next_selected = state.selected_channel

    if key in KEY_QUIT:
        should_quit = True
    elif key == KEY_TOGGLE:
        updated = handle_toggle(selected, ctx)
    elif key in KEY_BACKSPACE:
        updated = handle_backspace(ctx, selected)
    elif key == KEY_CONFIRM:
        updated = handle_confirm(selected)
    elif key != KEY_EXTENDED:
        updated, _ = handle_numeric_input(key, selected, ctx)
    else:
        next_key = msvcrt.getch()
        updated, new_selected = handle_extended_key(next_key, selected, ctx, state)
        if new_selected is not None:
            next_selected = new_selected

    channels = {**state.channels, state.selected_channel: updated}
    return UiState(next_selected, channels), should_quit


def run_tui_loop(psu: RigolDP900, voltage: float, is_on: bool) -> None:
    import msvcrt  # Windows-only

    channel_limits = {
        1: (CH1_MIN, CH1_MAX),
        2: (CH2_MIN, CH2_MAX),
        3: (CH3_MIN, CH3_MAX),
    }
    channels: dict[int, ChannelState] = {}
    for channel_id, (min_v, max_v) in channel_limits.items():
        start_voltage = clamp_voltage(voltage, min_v, max_v)
        channels[channel_id] = ChannelState(
            start_voltage,
            is_on,
            "ON" if is_on else "OFF",
            "",
        )
        apply_voltage(ChannelContext(psu, channel_id, min_v, max_v), start_voltage)
    state = UiState(1, channels)

    while True:
        boxes: list[list[str]] = []
        for channel_id in (1, 2, 3):
            channel = state.channels[channel_id]
            label = f"CH{channel_id}"
            is_selected = state.selected_channel == channel_id
            boxes.append(
                render_channel_box(label, channel.voltage, channel.status, is_selected)
            )
        draw_screen(boxes)
        key = msvcrt.getch()
        selected_channel = state.selected_channel
        min_v, max_v = channel_limits[selected_channel]
        ctx = ChannelContext(psu, selected_channel, min_v, max_v)
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
        print("\n".join(render_channel_box("CH1", voltage, "OFF", True)))
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
