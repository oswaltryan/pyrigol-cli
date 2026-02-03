import logging
from collections.abc import Mapping
from typing import Any, Protocol, cast

import pyvisa as visa
import pyvisa.constants as visa_constants
from pyvisa import errors as visa_errors


class _VisaSerialResource(Protocol):
    timeout: int | None
    baud_rate: int
    data_bits: int
    stop_bits: Any
    parity: Any
    read_termination: str | None
    write_termination: str | None

    def write(self, command: str) -> None: ...

    def read_raw(self) -> bytes: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


def _get_logger(name: str, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s %(name)-12s %(levelname)-8s %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


class _RigolDP900:
    def __init__(
        self,
        resource: str,
        loglevel: int = logging.INFO,
        timeout_ms: int = 5000,
        serial_settings: Mapping[str, Any] | None = None,
    ) -> None:
        self.logger = _get_logger(self.__class__.__name__, loglevel)

        try:
            resources = visa.ResourceManager()
            self.device = cast(_VisaSerialResource, resources.open_resource(resource))
            self.device.timeout = timeout_ms
            if resource.upper().startswith("ASRL"):
                settings = serial_settings or {}
                self.device.baud_rate = settings.get("baud_rate", 115200)
                self.device.data_bits = settings.get("data_bits", 8)
                self.device.stop_bits = settings.get(
                    "stop_bits", visa_constants.StopBits.one
                )
                self.device.parity = settings.get("parity", visa_constants.Parity.none)
                read_term = settings.get("read_termination", "\n")
                write_term = settings.get("write_termination", "\n")
                if read_term is not None:
                    self.device.read_termination = read_term
                if write_term is not None:
                    self.device.write_termination = write_term
        except visa.Error as error:
            message = getattr(error, "description", str(error))
            self.logger.critical(message)
            raise

    def send_command(self, command: str) -> None:
        self.logger.debug("Sent command: %s", command)
        self.device.write(command)

    def read_response(self) -> bytes:
        buffer = self.device.read_raw()
        self.logger.debug("Got response: %s", buffer)
        return buffer

    def query_command(self, command: str) -> str:
        buffer = self.device.query(command)
        filtered_buffer = buffer.replace("\n", "\\n")
        self.logger.debug("Query sent: %s, got: %s", command, filtered_buffer)
        return buffer

    class loglevel:
        INFO = logging.INFO
        WARNING = logging.WARNING
        ERROR = logging.ERROR
        CRITICAL = logging.CRITICAL
        DEBUG = logging.DEBUG

    def print_info(self) -> None:
        try:
            response = self.query_command("*IDN?")
        except visa_errors.VisaIOError as exc:
            self.logger.warning("*IDN? query failed: %s", exc)
            return
        response = response.strip()
        if response:
            self.logger.info("PSU information: %s", response)

    def set_voltage(self, channel: int = 1, voltage: float = 0) -> None:
        self.send_command(f":SOUR{channel}:VOLT {voltage}")
        self.logger.info("CH%s voltage set to %s V", channel, voltage)

    def output_state(self, channel: int = 1, state: int = 1) -> None:
        state_str = "ON" if state else "OFF"
        self.send_command(f":OUTP CH{channel},{state_str}")
        self.logger.info("CH%s output set to %s", channel, state_str)

    def close(self) -> None:
        self.device.close()
        self.logger.info("Closed USB session to power supply")


class RigolDP900(_RigolDP900):
    pass


class RigolDP932A(_RigolDP900):
    pass


class RigolDP932U(_RigolDP900):
    pass
