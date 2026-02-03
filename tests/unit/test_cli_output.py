from __future__ import annotations

import argparse
from typing import Any

from pyrigol.app import cli


class _FakePsu:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls: list[tuple[int, int]] = []

    def print_info(self) -> None:
        return None

    def set_voltage(self, _channel: int, _voltage: float) -> None:
        return None

    def output_state(self, channel: int, state: int) -> None:
        self.calls.append((channel, state))

    def close(self) -> None:
        return None


class _FakeRigolDP900(_FakePsu):
    class loglevel:
        INFO = 0

    last_instance: _FakeRigolDP900 | None = None

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        super().__init__()
        _FakeRigolDP900.last_instance = self


def test_output_off_turns_off_all_channels(monkeypatch: Any) -> None:
    def fake_parse_args() -> argparse.Namespace:
        return argparse.Namespace(
            list=False,
            resource="USB0::TEST::INSTR",
            timeout_ms=5000,
            baud_rate=115200,
            data_bits=8,
            parity="none",
            stop_bits="1",
            read_term="\n",
            write_term="\n",
            no_idn=True,
            ch1=1.0,
            ch2=1.0,
            ch3=1.0,
            output_on=None,
            output_off="all",
        )

    monkeypatch.setattr(cli, "RigolDP900", _FakeRigolDP900)
    monkeypatch.setattr(cli, "parse_args", fake_parse_args)

    cli.main()

    assert _FakeRigolDP900.last_instance is not None
    assert _FakeRigolDP900.last_instance.calls == [(1, 0), (2, 0), (3, 0)]


def test_output_on_single_channel(monkeypatch: Any) -> None:
    def fake_parse_args() -> argparse.Namespace:
        return argparse.Namespace(
            list=False,
            resource="USB0::TEST::INSTR",
            timeout_ms=5000,
            baud_rate=115200,
            data_bits=8,
            parity="none",
            stop_bits="1",
            read_term="\n",
            write_term="\n",
            no_idn=True,
            ch1=1.0,
            ch2=1.0,
            ch3=1.0,
            output_on="2",
            output_off=None,
        )

    monkeypatch.setattr(cli, "RigolDP900", _FakeRigolDP900)
    monkeypatch.setattr(cli, "parse_args", fake_parse_args)

    cli.main()

    assert _FakeRigolDP900.last_instance is not None
    assert _FakeRigolDP900.last_instance.calls == [(2, 1)]
