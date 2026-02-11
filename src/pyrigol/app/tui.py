from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, cast

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
MAX_FRAC_DIGITS = 3
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
KEY_ESCAPE = b"\x1b"
KEY_MENU = (b"\t",)
ESC_REVERSE = "\x1b[7m"
ESC_RESET = "\x1b[0m"
DIGIT_KEYS = tuple(str(d).encode() for d in range(10))
ALL_CHANNEL = 4
PRIMARY_CHANNELS = (1, 2, 3)
DEFAULT_STEP = 0.25
STEP_MIN = 0.0
STEP_MAX = 10.0
VOLTAGE_TOLERANCE = 1e-6


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
    channel_label: str, voltage_display: str, status: str, is_selected: bool
) -> list[str]:
    status_display = {
        "ON": " ON",
        "OFF": " OFF",
        "Mixed": " Mixed",
    }.get(status, status)
    if voltage_display == "Mixed":
        voltage_text = "  Voltage:  Mixed"
    else:
        voltage_text = f"  Voltage: {voltage_display.rjust(6)} V"
    status_text = f"  Status : {status_display:<3}"
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


def render_menu(settings: list[MenuItem], selected_index: int) -> list[str]:
    lines = [
        "+--------------------------+",
        f"|{_format_inner('MENU'.center(INNER_WIDTH), INNER_WIDTH)}|",
        f"|{_format_inner('', INNER_WIDTH)}|",
    ]
    for idx, item in enumerate(settings):
        text = f"{item.label}: {item.value}"
        line = f"|{_format_inner(text, INNER_WIDTH)}|"
        lines.append(_apply_reverse(line, idx == selected_index))
    lines.extend(
        [
            f"|{_format_inner('', INNER_WIDTH)}|",
            "+--------------------------+",
        ]
    )
    return lines


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
        input("Press Enter to exit program...")
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
    input("Press Enter to exit program...")
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
    boxes: list[list[str]],
    menu_lines: list[str],
    menu_open: bool,
    menu_editing: bool,
    step_size: float,
) -> None:
    os.system("cls")
    if menu_open:
        for line in menu_lines:
            print(line)
        print("")
        if menu_editing:
            print("Type a value. Enter to apply.")
        else:
            print("Up/Down: move")
            print("Enter: edit")
            print("Esc: back")
        return

    for row in zip(*boxes, strict=True):
        print("  ".join(row))
    print("")
    print("+--------------------------------------------------------+")
    print("| Left/Right: switch channel                             |")
    print("|   Spacebar: toggle selected channel ON/OFF             |")
    print(f"|    Up/Down: nudge by {step_size:.3f} V                           |")
    print("|        0-9: type a voltage (e.g. 5.00) enter to apply  |")
    print("|        Tab: menu                                       |")
    print("|        Esc: exit                                       |")
    print("+--------------------------------------------------------+")


def clamp_voltage(voltage: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, voltage))


def cycle_channel(current: int, channels: dict[int, ChannelState], direction: int) -> int:
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
    menu_open: bool

    menu_index: int
    auto_apply: bool
    voltage_step: float
    menu_editing: bool
    menu_input_buffer: str


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    value: str
    editable: bool


def update_state(state: UiState, **updates: Any) -> UiState:
    return UiState(
        updates.get("selected_channel", state.selected_channel),
        updates.get("channels", state.channels),
        updates.get("menu_open", state.menu_open),
        updates.get("menu_index", state.menu_index),
        updates.get("auto_apply", state.auto_apply),
        updates.get("voltage_step", state.voltage_step),
        updates.get("menu_editing", state.menu_editing),
        updates.get("menu_input_buffer", state.menu_input_buffer),
    )


def build_menu_settings(state: UiState) -> list[MenuItem]:
    step_value = (
        state.menu_input_buffer
        if state.menu_editing and state.menu_input_buffer
        else f"{state.voltage_step:.{MAX_FRAC_DIGITS}f}"
    )
    return [
        MenuItem("voltage_step", "Voltage Step Size", f"{step_value} V", True),
        MenuItem("auto_apply", "Auto-Apply", "On" if state.auto_apply else "Off", True),
    ]


def apply_voltage(ctx: ChannelContext, value: float) -> None:
    if ctx.selected_channel == ALL_CHANNEL:
        return
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


def handle_backspace(ctx: ChannelContext, channel: ChannelState, auto_apply: bool) -> ChannelState:
    if not channel.input_buffer:
        return channel

    updated = channel.input_buffer[:-1]
    if not updated:
        return ChannelState(channel.voltage, channel.is_on, channel.status, updated)

    buffer_value, voltage, applied = try_apply_candidate(updated, channel.voltage, ctx)
    if applied:
        if auto_apply:
            apply_voltage(ctx, voltage)
        return ChannelState(voltage, channel.is_on, channel.status, buffer_value)

    return ChannelState(channel.voltage, channel.is_on, channel.status, updated)


def handle_numeric_input(
    key: bytes,
    channel: ChannelState,
    ctx: ChannelContext,
    auto_apply: bool,
) -> tuple[ChannelState, bool]:
    candidate = try_build_candidate(channel.input_buffer, key)
    if candidate is None:
        return channel, False

    buffer_value, voltage, applied = try_apply_candidate(candidate, channel.voltage, ctx)
    if not applied:
        return channel, False

    if auto_apply:
        apply_voltage(ctx, voltage)
    return ChannelState(voltage, channel.is_on, channel.status, buffer_value), True


def handle_adjustment_key(
    key: bytes,
    channel: ChannelState,
    ctx: ChannelContext,
    auto_apply: bool,
    step_size: float,
) -> tuple[ChannelState, bool]:
    if key == KEY_UP:
        voltage = clamp_voltage(channel.voltage + step_size, ctx.min_v, ctx.max_v)
        if auto_apply:
            apply_voltage(ctx, voltage)
        return ChannelState(voltage, channel.is_on, channel.status, ""), True
    if key == KEY_DOWN:
        voltage = clamp_voltage(channel.voltage - step_size, ctx.min_v, ctx.max_v)
        if auto_apply:
            apply_voltage(ctx, voltage)
        return ChannelState(voltage, channel.is_on, channel.status, ""), True
    return channel, False


def handle_toggle(channel: ChannelState, ctx: ChannelContext) -> ChannelState:
    is_on = not channel.is_on
    status = "ON" if is_on else "OFF"
    if ctx.selected_channel != ALL_CHANNEL:
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
    updated, _ = handle_adjustment_key(key, channel, ctx, state.auto_apply, state.voltage_step)
    return updated, None


def apply_all_state(
    state: UiState,
    previous: ChannelState,
    channel_limits: dict[int, tuple[float, float]],
    psu: RigolDP900,
    auto_apply: bool,
    force_voltage_apply: bool = False,
) -> UiState:
    all_state = state.channels[ALL_CHANNEL]
    channels = dict(state.channels)
    if all_state.is_on != previous.is_on:
        for channel_id in PRIMARY_CHANNELS:
            psu.output_state(channel_id, 1 if all_state.is_on else 0)
            channel = channels[channel_id]
            channels[channel_id] = ChannelState(
                channel.voltage,
                all_state.is_on,
                "ON" if all_state.is_on else "OFF",
                channel.input_buffer,
            )

    if (auto_apply or force_voltage_apply) and all_state.voltage != previous.voltage:
        for channel_id in PRIMARY_CHANNELS:
            min_v, max_v = channel_limits[channel_id]
            clamped = clamp_voltage(all_state.voltage, min_v, max_v)
            psu.set_voltage(channel_id, clamped)
            channel = channels[channel_id]
            channels[channel_id] = ChannelState(
                clamped,
                channel.is_on,
                channel.status,
                channel.input_buffer,
            )

    return UiState(
        state.selected_channel,
        channels,
        state.menu_open,
        state.menu_index,
        state.auto_apply,
        state.voltage_step,
        state.menu_editing,
        state.menu_input_buffer,
    )


def sync_all_status(state: UiState) -> UiState:
    all_state = state.channels[ALL_CHANNEL]
    channel_states = [state.channels[ch] for ch in PRIMARY_CHANNELS]
    any_on = any(ch.is_on for ch in channel_states)
    all_on = all(ch.is_on for ch in channel_states)
    if all_on:
        status = "ON"
        is_on = True
    elif any_on:
        status = "Mixed"
        is_on = False
    else:
        status = "OFF"
        is_on = False

    if status == all_state.status and is_on == all_state.is_on:
        return state

    updated = ChannelState(
        all_state.voltage,
        is_on,
        status,
        all_state.input_buffer,
    )
    channels = {**state.channels, ALL_CHANNEL: updated}
    return UiState(
        state.selected_channel,
        channels,
        state.menu_open,
        state.menu_index,
        state.auto_apply,
        state.voltage_step,
        state.menu_editing,
        state.menu_input_buffer,
    )


def cycle_menu_index(current: int, delta: int, total: int) -> int:
    if total <= 0:
        return 0
    return (current + delta) % total


def apply_menu_action(state: UiState) -> UiState:
    settings = build_menu_settings(state)
    if not settings:
        return state
    index = min(state.menu_index, len(settings) - 1)
    item = settings[index]
    if not item.editable:
        return state
    if item.key == "voltage_step":
        return UiState(
            state.selected_channel,
            state.channels,
            state.menu_open,
            index,
            state.auto_apply,
            state.voltage_step,
            True,
            "",
        )
    if item.key == "auto_apply":
        return UiState(
            state.selected_channel,
            state.channels,
            state.menu_open,
            index,
            not state.auto_apply,
            state.voltage_step,
            state.menu_editing,
            state.menu_input_buffer,
        )
    return state


def update_menu_index(state: UiState, delta: int) -> UiState:
    total = len(build_menu_settings(state))
    next_index = cycle_menu_index(state.menu_index, delta, total)
    return update_state(state, menu_index=next_index)


def handle_menu_editing_key(key: bytes, state: UiState, ctx: ChannelContext) -> UiState:
    step_ctx = ChannelContext(ctx.psu, ctx.selected_channel, STEP_MIN, STEP_MAX)
    step_state = ChannelState(state.voltage_step, False, "", state.menu_input_buffer)
    if key == KEY_CONFIRM:
        return update_state(
            state,
            voltage_step=step_state.voltage,
            menu_editing=False,
            menu_input_buffer="",
        )
    if key in KEY_BACKSPACE:
        updated = handle_backspace(step_ctx, step_state, False)
        return update_state(
            state,
            voltage_step=updated.voltage,
            menu_input_buffer=updated.input_buffer,
        )
    if key != KEY_EXTENDED:
        updated, _ = handle_numeric_input(key, step_state, step_ctx, False)
        return update_state(
            state,
            voltage_step=updated.voltage,
            menu_input_buffer=updated.input_buffer,
        )
    return state


def handle_menu_key(
    key: bytes,
    state: UiState,
    ctx: ChannelContext,
    msvcrt: Any,
) -> UiState:
    if key == KEY_ESCAPE:
        return update_state(
            state,
            menu_open=False,
            menu_editing=False,
            menu_input_buffer="",
        )
    if state.menu_editing:
        return handle_menu_editing_key(key, state, ctx)
    if key == KEY_CONFIRM:
        return apply_menu_action(state)
    if key != KEY_EXTENDED:
        return state

    next_key = msvcrt.getch()
    delta = 0
    if next_key == KEY_UP:
        delta = -1
    elif next_key == KEY_DOWN:
        delta = 1
    if delta:
        return update_menu_index(state, delta)
    return state


def handle_main_escape(
    state: UiState, selected: ChannelState, ctx: ChannelContext, msvcrt: Any
) -> tuple[UiState, bool]:
    if selected.input_buffer:
        updated = ChannelState(selected.voltage, selected.is_on, selected.status, "")
        channels = {**state.channels, state.selected_channel: updated}
        return update_state(state, channels=channels), False
    return state, confirm_exit(msvcrt)


def handle_non_extended_key(
    key: bytes, selected: ChannelState, ctx: ChannelContext, state: UiState
) -> tuple[ChannelState, bool]:
    if key == KEY_TOGGLE:
        return handle_toggle(selected, ctx), False
    if key in KEY_BACKSPACE:
        return handle_backspace(ctx, selected, state.auto_apply), False
    if key == KEY_CONFIRM:
        return handle_confirm(selected), True
    updated, _ = handle_numeric_input(key, selected, ctx, state.auto_apply)
    return updated, False


def handle_extended_input(
    msvcrt: Any, selected: ChannelState, ctx: ChannelContext, state: UiState
) -> tuple[ChannelState, int]:
    next_key = msvcrt.getch()
    updated, new_selected = handle_extended_key(next_key, selected, ctx, state)
    next_selected = state.selected_channel if new_selected is None else new_selected
    return updated, next_selected


def handle_main_key(
    key: bytes,
    state: UiState,
    ctx: ChannelContext,
    msvcrt: Any,
    channel_limits: dict[int, tuple[float, float]],
) -> tuple[UiState, bool]:
    selected = state.channels[state.selected_channel]
    if key == KEY_ESCAPE:
        return handle_main_escape(state, selected, ctx, msvcrt)

    if key == KEY_EXTENDED:
        updated, next_selected = handle_extended_input(msvcrt, selected, ctx, state)
        confirm_apply = False
    else:
        updated, confirm_apply = handle_non_extended_key(key, selected, ctx, state)
        next_selected = state.selected_channel

    channels = {**state.channels, state.selected_channel: updated}
    next_state = update_state(
        state,
        selected_channel=next_selected,
        channels=channels,
    )
    if state.selected_channel == ALL_CHANNEL:
        next_state = apply_all_state(
            next_state,
            selected,
            channel_limits,
            ctx.psu,
            state.auto_apply,
        )
    if confirm_apply and not state.auto_apply:
        if state.selected_channel == ALL_CHANNEL:
            next_state = apply_all_state(
                next_state,
                selected,
                channel_limits,
                ctx.psu,
                state.auto_apply,
                True,
            )
        else:
            apply_voltage(ctx, updated.voltage)
    return next_state, False


def handle_key(
    key: bytes,
    state: UiState,
    ctx: ChannelContext,
    msvcrt: Any,
    channel_limits: dict[int, tuple[float, float]],
) -> tuple[UiState, bool]:
    if key in KEY_MENU and not state.menu_open:
        return (
            update_state(
                state,
                menu_open=True,
                menu_editing=False,
                menu_input_buffer="",
            ),
            False,
        )
    if state.menu_open:
        return handle_menu_key(key, state, ctx, msvcrt), False
    return handle_main_key(key, state, ctx, msvcrt, channel_limits)


def _load_msvcrt() -> Any:
    return importlib.import_module("msvcrt")


def read_output_states(psu: RigolDP900, fallback: bool) -> dict[int, bool]:
    states: dict[int, bool] = {}
    for channel in PRIMARY_CHANNELS:
        try:
            states[channel] = psu.get_output_state(channel)
        except Exception:
            states[channel] = fallback
    return states


def read_voltages(psu: RigolDP900, fallback: float) -> dict[int, float]:
    values: dict[int, float] = {}
    for channel in PRIMARY_CHANNELS:
        try:
            values[channel] = psu.get_voltage(channel)
        except Exception:
            values[channel] = fallback
    return values


def derive_all_voltage(voltages: dict[int, float], fallback: float) -> float:
    for channel in PRIMARY_CHANNELS:
        if channel in voltages:
            return voltages[channel]
    return fallback


def build_channel_limits() -> dict[int, tuple[float, float]]:
    return {
        1: (CH1_MIN, CH1_MAX),
        2: (CH2_MIN, CH2_MAX),
        3: (CH3_MIN, CH3_MAX),
        ALL_CHANNEL: (
            min(CH1_MIN, CH2_MIN, CH3_MIN),
            max(CH1_MAX, CH2_MAX, CH3_MAX),
        ),
    }


def initialize_state(
    psu: RigolDP900,
    voltage: float,
    is_on: bool,
    channel_limits: dict[int, tuple[float, float]],
) -> UiState:
    output_states = read_output_states(psu, is_on)
    voltages = read_voltages(psu, voltage)
    all_voltage = derive_all_voltage(voltages, voltage)
    channels: dict[int, ChannelState] = {}
    for channel_id, (min_v, max_v) in channel_limits.items():
        raw_voltage = (
            all_voltage if channel_id == ALL_CHANNEL else voltages.get(channel_id, voltage)
        )
        start_voltage = clamp_voltage(raw_voltage, min_v, max_v)
        channel_is_on = output_states[channel_id] if channel_id in PRIMARY_CHANNELS else is_on
        channels[channel_id] = ChannelState(
            start_voltage,
            channel_is_on,
            "ON" if channel_is_on else "OFF",
            "",
        )
        apply_voltage(ChannelContext(psu, channel_id, min_v, max_v), start_voltage)
    state = UiState(1, channels, False, 0, True, DEFAULT_STEP, False, "")
    return sync_all_status(state)


def build_boxes(state: UiState) -> list[list[str]]:
    boxes: list[list[str]] = []
    primary_voltages = [state.channels[ch].voltage for ch in PRIMARY_CHANNELS]
    all_voltage = primary_voltages[0] if primary_voltages else 0.0
    all_mixed = any(abs(v - all_voltage) > VOLTAGE_TOLERANCE for v in primary_voltages[1:])
    for channel_id in (*PRIMARY_CHANNELS, ALL_CHANNEL):
        channel = state.channels[channel_id]
        label = "ALL" if channel_id == ALL_CHANNEL else f"CH{channel_id}"
        is_selected = state.selected_channel == channel_id
        if channel_id == ALL_CHANNEL and all_mixed:
            voltage_display = "Mixed"
        else:
            voltage_display = f"{channel.voltage:.3f}"
        boxes.append(render_channel_box(label, voltage_display, channel.status, is_selected))
    return boxes


def confirm_exit(msvcrt: Any) -> bool:
    prompt = "Would you like to exit the program (Y/N)? "
    print(prompt, end="", flush=True)
    while True:
        key = msvcrt.getch()
        if key in (b"y", b"Y"):
            print("Y")
            return True
        if key in (b"n", b"N"):
            print("N")
            return False
        if key in (b"\r", b"\n"):
            continue
        if key == KEY_EXTENDED:
            msvcrt.getch()


def run_tui_loop(psu: RigolDP900, voltage: float, is_on: bool) -> None:
    msvcrt = cast(Any, _load_msvcrt())  # Windows-only

    channel_limits = build_channel_limits()
    state = initialize_state(psu, voltage, is_on, channel_limits)

    while True:
        boxes = build_boxes(state)
        menu_settings = build_menu_settings(state)
        menu_lines = render_menu(menu_settings, state.menu_index)
        draw_screen(
            boxes,
            menu_lines,
            state.menu_open,
            state.menu_editing,
            state.voltage_step,
        )
        key = msvcrt.getch()
        selected_channel = state.selected_channel
        min_v, max_v = channel_limits[selected_channel]
        ctx = ChannelContext(psu, selected_channel, min_v, max_v)
        state, should_quit = handle_key(key, state, ctx, msvcrt, channel_limits)
        state = sync_all_status(state)
        if should_quit:
            break
        time.sleep(0.02)


def main() -> int:
    args = parse_args()
    voltage = 5.00
    is_on = False

    if sys.platform != "win32":
        print("This TUI input loop currently supports Windows only.")
        print("\n".join(render_channel_box("CH1", f"{voltage:.3f}", "OFF", True)))
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
