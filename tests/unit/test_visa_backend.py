from __future__ import annotations

from typing import Any

import pyvisa as visa

from pyrigol.app import cli
from pyrigol.rigol.dp900 import RigolDP900


class _FakeDevice:
    def __init__(self) -> None:
        self.timeout: int | None = None

    def close(self) -> None:
        return None

    def write(self, _command: str) -> None:
        return None

    def read_raw(self) -> bytes:
        return b""

    def query(self, _command: str) -> str:
        return ""


class _FakeResourceManager:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def list_resources(self, _pattern: str | None = None) -> tuple[str, ...]:
        return ("USB0::0x1AB1::0xA4A8::DP9A271M00086::INSTR",)

    def open_resource(self, _resource: str) -> _FakeDevice:
        return _FakeDevice()


class _EmptyUsbResourceManager(_FakeResourceManager):
    def list_resources(self, _pattern: str | None = None) -> tuple[str, ...]:
        if _pattern:
            return ()
        return ("ASRL1::INSTR",)


def test_list_resources_uses_default_backend(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_resource_manager(*args: Any, **kwargs: Any) -> _FakeResourceManager:
        called["args"] = args
        called["kwargs"] = kwargs
        return _FakeResourceManager(*args, **kwargs)

    monkeypatch.setattr(visa, "ResourceManager", fake_resource_manager)

    cli.list_resources()

    assert called["args"] == ()
    assert called["kwargs"] == {}


def test_driver_uses_default_backend(monkeypatch: Any) -> None:
    called: dict[str, Any] = {}

    def fake_resource_manager(*args: Any, **kwargs: Any) -> _FakeResourceManager:
        called["args"] = args
        called["kwargs"] = kwargs
        return _FakeResourceManager(*args, **kwargs)

    monkeypatch.setattr(visa, "ResourceManager", fake_resource_manager)

    RigolDP900(
        "USB0::0x1AB1::0xA4A8::DP9A271M00086::INSTR",
        RigolDP900.loglevel.INFO,
    ).close()

    assert called["args"] == ()
    assert called["kwargs"] == {}


def test_list_resources_warns_when_backend_missing(
    monkeypatch: Any, capsys: Any
) -> None:
    def fake_resource_manager(*_args: Any, **_kwargs: Any) -> _FakeResourceManager:
        raise RuntimeError("no visa library")

    monkeypatch.setattr(visa, "ResourceManager", fake_resource_manager)

    cli.list_resources()

    captured = capsys.readouterr()
    assert "NI-VISA is not available" in captured.err


def test_list_resources_warns_when_no_usb_device(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(visa, "ResourceManager", lambda: _EmptyUsbResourceManager())

    cli.list_resources()

    captured = capsys.readouterr()
    assert "No USB VISA resources found" in captured.err
    assert "ASRL1::INSTR" in captured.out
