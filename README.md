# pyrigol

Python control for Rigol DP900 series power supplies over USB or serial using
PyVISA.

![Rigol DP932A power supply](docs/images/DP932a.png)

## Requirements

- Python 3.12+
- `uv`
- NI-VISA (Windows) or another VISA implementation that provides `visa32.dll`
  for USB discovery
  - Download: https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html#585834

## Install

```sh
uv sync
```

## Quickstart

List VISA resources:

```sh
uv run pyrigol --list
```

Set voltages and enable outputs over USB:

```sh
uv run pyrigol --resource "USB0::0x1AB1::0x0E11::DP9XXXXXXXX::INSTR" --ch1 5.0 --ch2 3.3 --ch3 1.8 --output-on
```

Turn outputs off after setting voltages:

```sh
uv run pyrigol --resource "USB0::0x1AB1::0x0E11::DP9XXXXXXXX::INSTR" --ch1 5.0 --ch2 3.3 --ch3 1.8 --output-off
```

Single-channel output control:

```sh
uv run pyrigol --resource "USB0::0x1AB1::0x0E11::DP9XXXXXXXX::INSTR" --ch1 5.0 --ch2 3.3 --ch3 1.8 --output-on 2
```

## EFT Test Script

The EFT script steps all three channels together based on Enter presses. It
auto-discovers the first USB VISA resource when no arguments are provided.

```sh
uv run python scripts/eft_test_script.py
```

To use a specific resource:

```sh
uv run python scripts/eft_test_script.py --resource "USB0::0x1AB1::0x0E11::DP9XXXXXXXX::INSTR"
```

## Serial (ASRL) Notes

If your device enumerates as `ASRLx::INSTR`, use the serial options:

```sh
uv run pyrigol --resource "ASRL4::INSTR" --baud-rate 115200 --ch1 3.3 --ch2 3.3 --ch3 1.8 --output-on
```

If `*IDN?` times out on serial, try skipping it and adjusting terminations:

```sh
uv run pyrigol --resource "ASRL4::INSTR" --baud-rate 115200 --read-term "
" --write-term "
" --no-idn --ch1 3.3 --ch2 3.3 --ch3 1.8 --output-on
```

## Troubleshooting

- "NI-VISA is not available": Install NI-VISA and ensure `visa32.dll` is
  present on the system PATH.
- "No USB VISA resources found": Confirm the device is connected via USB and
  the driver is installed. Some devices enumerate under NI-VISA only.

## Development

Install pre-commit hooks:

```sh
uv run pre-commit install
```
