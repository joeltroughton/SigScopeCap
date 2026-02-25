#!/usr/bin/env python3
"""
Siglent SDS 1104X-E Waveform Capture Script

Captures displayed waveforms from a USB-connected Siglent oscilloscope
and saves the data to a CSV file.

Requirements:
    pip install pyvisa

    You also need a VISA backend. The easiest option on Windows:
      - Install NI-VISA runtime from:
        https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html

    Alternative (pure Python, no NI-VISA needed):
      pip install pyvisa-py pyusb
      Then use Zadig (https://zadig.akeo.ie/) to install the libusb-win32
      driver for the scope's USB interface.

Usage:
    python scope_capture.py                     # Auto-detect scope, capture all active channels
    python scope_capture.py -o mydata.csv       # Specify output filename
    python scope_capture.py -c 1,3              # Capture only CH1 and CH3
    python scope_capture.py -a "USB0::..."      # Specify VISA address manually
    python scope_capture.py -n 50000            # Decimate to ~50k points max in the CSV
    python scope_capture.py --list              # List available VISA resources
"""

import pyvisa
import csv
import sys
import time
import argparse
from datetime import datetime


def parse_value(response):
    """Parse a numeric value from a Siglent SCPI response.

    Siglent responses include units like 'V', 's', 'Sa/s', etc.
    Examples:
        'C1:VDIV 2.00E-01V'  -> 0.2
        'TDIV 1.00E-03s'     -> 0.001
        'SARA 5.00E+08Sa/s'  -> 500000000.0
        'SARA 500MSa/s'      -> 500000000.0
    """
    response = response.strip()
    value_str = response.split()[-1] if response.split() else response

    # Strip known unit suffixes (longest first to avoid partial matches)
    for unit in ['Sa/s', 'sa/s', 'pts', 'Pts', 'Hz', 'hz', 'V', 'v', 's', 'S']:
        if value_str.endswith(unit):
            value_str = value_str[:-len(unit)]
            break

    # Handle SI prefixes at the end of the numeric string
    si_prefixes = {
        'G': 1e9, 'M': 1e6, 'k': 1e3,
        'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12,
    }
    multiplier = 1.0
    if value_str and value_str[-1] in si_prefixes:
        multiplier = si_prefixes[value_str[-1]]
        value_str = value_str[:-1]

    return float(value_str) * multiplier


def connect_scope(visa_address=None):
    """Connect to the Siglent oscilloscope via VISA."""
    try:
        rm = pyvisa.ResourceManager()
    except Exception:
        # Fall back to pyvisa-py backend if NI-VISA is not installed
        rm = pyvisa.ResourceManager('@py')

    if visa_address:
        scope = rm.open_resource(visa_address)
        scope.timeout = 5000
        idn = scope.query('*IDN?').strip()
        print(f"Connected to: {idn}")
        return scope

    # Auto-detect: scan USB resources for a Siglent scope
    resources = rm.list_resources()
    if not resources:
        print("ERROR: No VISA resources found.")
        print("Make sure the scope is connected via USB and a VISA backend is installed.")
        print("Run with --list to see available resources.")
        sys.exit(1)

    for res in resources:
        if 'USB' in res.upper():
            try:
                scope = rm.open_resource(res)
                scope.timeout = 5000
                idn = scope.query('*IDN?').strip()
                if 'siglent' in idn.lower():
                    print(f"Connected to: {idn}")
                    return scope
                scope.close()
            except Exception as e:
                print(f"  Skipping {res}: {e}")

    print("ERROR: No Siglent oscilloscope found on USB.")
    print(f"Available resources: {resources}")
    sys.exit(1)


def list_resources():
    """List all available VISA resources."""
    try:
        rm = pyvisa.ResourceManager()
    except Exception:
        rm = pyvisa.ResourceManager('@py')

    resources = rm.list_resources()
    if not resources:
        print("No VISA resources found.")
    else:
        print("Available VISA resources:")
        for res in resources:
            print(f"  {res}")
            try:
                inst = rm.open_resource(res)
                inst.timeout = 3000
                idn = inst.query('*IDN?').strip()
                print(f"    -> {idn}")
                inst.close()
            except Exception:
                pass


def get_active_channels(scope):
    """Determine which channels (C1-C4) are currently displayed."""
    active = []
    for ch in range(1, 5):
        try:
            resp = scope.query(f'C{ch}:TRA?').strip()
            if 'ON' in resp.upper():
                active.append(ch)
        except Exception:
            pass
    return active


def capture_channel(scope, channel, tdiv, sara):
    """Capture waveform data from a single channel.

    Returns:
        voltages: list of voltage values
        info: dict with channel parameters
    """
    ch = f'C{channel}'

    # Read vertical scale parameters
    vdiv = parse_value(scope.query(f'{ch}:VDIV?'))
    ofst = parse_value(scope.query(f'{ch}:OFST?'))

    print(f"  {ch}: VDIV={vdiv:.3g} V, OFST={ofst:.3g} V")

    # Configure waveform transfer: every point, all points, from the start
    scope.write('WFSU SP,1,NP,0,FP,0')
    time.sleep(0.1)

    # Request waveform data
    scope.write(f'{ch}:WF? DAT2')
    time.sleep(0.3)

    # Read the raw binary response
    raw = scope.read_raw()

    # Parse IEEE 488.2 definite-length block header
    # Response format: "C1:WF ALL,#9<9-digit-length><binary-data>\n\n"
    marker = raw.find(b'#9')
    if marker == -1:
        raise ValueError(f"Could not find data block header in {ch} response")

    data_len = int(raw[marker + 2 : marker + 11])
    data_start = marker + 11
    wave_bytes = raw[data_start : data_start + data_len]

    # Convert raw bytes to voltage values.
    # Siglent DAT2 waveform bytes are not centered at 128. Per Siglent's
    # programming guide, bytes 0..127 map directly to positive codes, and
    # bytes 128..255 wrap into negative codes via (code - 255).
    # Using a 128-centered conversion produces artificial +/- full-scale
    # spikes and the wrong edge shape.
    code_per_div = 25.0
    voltages = []
    for b in wave_bytes:
        code = b - 255 if b > 127 else b
        voltage = (code / code_per_div) * vdiv - ofst
        voltages.append(voltage)

    return voltages, {'vdiv': vdiv, 'ofst': ofst, 'num_points': len(voltages)}


def save_csv(filename, times, channel_data):
    """Save waveform data to a CSV file."""
    channels = sorted(channel_data.keys())

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)

        # Header
        header = ['Time (s)'] + [f'CH{ch} (V)' for ch in channels]
        writer.writerow(header)

        # Data rows
        for i in range(len(times)):
            row = [f'{times[i]:.10e}']
            for ch in channels:
                volts = channel_data[ch]
                if i < len(volts):
                    row.append(f'{volts[i]:.6e}')
                else:
                    row.append('')
            writer.writerow(row)

    print(f"\nSaved {len(times)} samples x {len(channels)} channel(s) to: {filename}")


def main():
    parser = argparse.ArgumentParser(
        description='Capture waveforms from a Siglent SDS 1104X-E oscilloscope via USB'
    )
    parser.add_argument(
        '-o', '--output', default=None,
        help='Output CSV filename (default: scope_<timestamp>.csv)'
    )
    parser.add_argument(
        '-a', '--address', default=None,
        help='VISA resource address (auto-detect if omitted)'
    )
    parser.add_argument(
        '-c', '--channels', default=None,
        help='Comma-separated channel numbers to capture, e.g. "1,3" (default: all displayed)'
    )
    parser.add_argument(
        '-n', '--maxpoints', type=int, default=None,
        help='Max number of points to save in the CSV (evenly decimates if needed)'
    )
    parser.add_argument(
        '--list', action='store_true',
        help='List available VISA resources and exit'
    )
    args = parser.parse_args()

    if args.list:
        list_resources()
        return

    # Default output filename
    if args.output is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f'scope_{timestamp}.csv'

    # Connect
    scope = connect_scope(args.address)
    scope.timeout = 30000                   # 30 s for large transfers
    scope.chunk_size = 20 * 1024 * 1024     # 20 MB read buffer

    try:
        # Determine channels to capture
        if args.channels:
            channels = [int(c.strip()) for c in args.channels.split(',')]
        else:
            channels = get_active_channels(scope)
            if not channels:
                print("No active channels detected. Defaulting to CH1.")
                channels = [1]

        print(f"Channels to capture: {', '.join(f'CH{c}' for c in channels)}")

        # Stop acquisition so the waveform is stable during readout
        scope.write('STOP')
        time.sleep(0.5)

        # Read time-base parameters (same for all channels)
        tdiv = parse_value(scope.query('TDIV?'))
        sara = parse_value(scope.query('SARA?'))
        print(f"Time base: TDIV={tdiv:.3g} s, Sample rate={sara:.3g} Sa/s")

        # Capture each channel
        channel_data = {}
        for ch in channels:
            print(f"\nCapturing CH{ch}...")
            try:
                voltages, info = capture_channel(scope, ch, tdiv, sara)
                channel_data[ch] = voltages
                print(f"  {info['num_points']} points captured")
            except Exception as e:
                print(f"  ERROR on CH{ch}: {e}")

        if not channel_data:
            print("\nNo waveform data was captured!")
            sys.exit(1)

        # Build the time axis (centered at t=0 for the trigger point)
        num_points = max(len(v) for v in channel_data.values())
        dt = 1.0 / sara
        times = [(i - num_points / 2) * dt for i in range(num_points)]

        # Decimate if --maxpoints was specified
        if args.maxpoints and num_points > args.maxpoints:
            skip = num_points // args.maxpoints
            if skip < 1:
                skip = 1
            times = times[::skip]
            channel_data = {ch: v[::skip] for ch, v in channel_data.items()}
            print(f"\nDecimated: keeping every {skip}th sample "
                  f"({num_points} -> {len(times)} points)")

        # Save
        save_csv(args.output, times, channel_data)

    finally:
        scope.close()

    print("Done!")


if __name__ == '__main__':
    main()
