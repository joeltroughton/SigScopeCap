# ScopeCap: Siglent SDS Waveform Capture

Capture displayed waveforms from a USB-connected Siglent oscilloscope and save them to CSV.

This project currently includes a single script: `scope_capture.py`.

## Features

- Auto-detects a connected Siglent scope over VISA (USB)
- Captures one or more channels (CH1-CH4)
- Reads full waveform memory and converts to voltage values
- Saves `Time (s)` + channel voltages to CSV
- Optional decimation to reduce CSV size

## Tested Scope

- Siglent SDS 1104X-E

It may work with other Siglent SDS models that support the same SCPI waveform commands.

## Requirements

- Python 3.8+
- `pyvisa`
- A VISA backend:
  - Option A (recommended on Windows): NI-VISA runtime
  - Option B (pure Python): `pyvisa-py` + `pyusb` (and Zadig/libusb on Windows)

## Installation

```bash
pip install pyvisa
```

If NI-VISA is not installed, install pure-Python backend dependencies:

```bash
pip install pyvisa-py pyusb
```

## Quick Start

1. Connect scope to your computer over USB.
2. (Optional) list detected VISA resources:

```bash
python scope_capture.py --list
```

3. Capture all currently displayed channels:

```bash
python scope_capture.py
```

This writes a file named like:

```text
scope_YYYYMMDD_HHMMSS.csv
```

## Usage

```bash
python scope_capture.py [options]
```

Options:

- `-o, --output <file>`: output CSV filename
- `-a, --address <visa_resource>`: manually specify VISA resource
- `-c, --channels <list>`: comma-separated channel list (example: `1,3`)
- `-n, --maxpoints <int>`: cap CSV points via even decimation
- `--list`: list available VISA resources and exit

Examples:

```bash
# Auto-detect scope, capture displayed channels
python scope_capture.py

# Capture CH1 and CH3 only
python scope_capture.py -c 1,3

# Save to custom filename
python scope_capture.py -o capture.csv

# Limit CSV to about 50k points
python scope_capture.py -n 50000

# Use explicit VISA resource
python scope_capture.py -a "USB0::0xF4EC::0xEE38::SDSMMDXXXXXXXX::INSTR"
```

## Output Format

CSV columns:

- `Time (s)`
- `CH1 (V)`, `CH2 (V)`, ...

Notes:

- Time is generated from sample rate and centered around `t = 0`.
- Voltage values are reconstructed from Siglent `DAT2` waveform bytes.
- If channels have unequal lengths, missing points are left blank in the CSV.

## Scope State Behavior

The script sends `STOP` before readout so waveform memory stays stable during transfer.

After capture, the scope may remain stopped. Press `RUN/STOP` on the scope front panel to resume live acquisition.


