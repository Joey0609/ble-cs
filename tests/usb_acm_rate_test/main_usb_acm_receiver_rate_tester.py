#!/usr/bin/env python3
"""Measure native USB CDC receive throughput; requires pyserial."""
import argparse
import math
import sys
import time


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return number


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def measure(port, args):
    # Read and discard during startup, without repeatedly flushing the driver.
    # Start the measurement clock BEFORE the first counted read.
    buffer = bytearray(args.chunk_size)
    warmup_end = time.perf_counter() + args.warmup
    while time.perf_counter() < warmup_end:
        port.readinto(buffer)

    total = interval_bytes = reads = 0
    started = previous = time.perf_counter()
    deadline = started + args.duration
    print("Measuring received bytes; MB/s is decimal. Ctrl-C stops the test.", flush=True)
    try:
        while time.perf_counter() < deadline:
            count = port.readinto(buffer)
            total += count
            interval_bytes += count
            reads += 1
            now = time.perf_counter()
            if now - previous >= args.interval:
                print(
                    f"{now - started:7.2f} s  "
                    f"interval {interval_bytes / (now - previous) / 1e6:8.3f} MB/s  "
                    f"average {total / (now - started) / 1e6:8.3f} MB/s",
                    flush=True,
                )
                previous, interval_bytes = now, 0
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.perf_counter() - started
        rate = total / elapsed
        print(
            f"\nReceived {total:,} bytes in {elapsed:.3f} s ({reads:,} reads)\n"
            f"Average: {rate / 1e6:.3f} MB/s | {rate / 2**20:.3f} MiB/s | "
            f"{rate * 8 / 1e6:.3f} Mbit/s"
        )
    if total == 0:
        print("No data received. Check firmware, native USB port, and DTR.", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="e.g. /dev/cu.usbmodem1302")
    parser.add_argument("--baudrate", type=positive_int, default=115200,
                        help="CDC line coding, not USB speed (default: 115200)")
    parser.add_argument("--duration", type=positive_float, default=30.0,
                        help="measurement seconds, excluding warmup (default: 30)")
    parser.add_argument("--warmup", type=positive_float, default=2.0,
                        help="discard initial data for this many seconds (default: 2)")
    parser.add_argument("--interval", type=positive_float, default=1.0,
                        help="progress report interval in seconds (default: 1)")
    parser.add_argument("--chunk-size", type=positive_int, default=16384,
                        help="bytes requested per read (default: 16384)")
    args = parser.parse_args()
    try:
        import serial
    except ImportError:
        parser.exit(2, "Install the dependency with: python3 -m pip install pyserial\n")
    try:
        with serial.Serial(args.port, baudrate=args.baudrate, timeout=0.1,
                           xonxoff=False, rtscts=False, dsrdtr=False) as port:
            if hasattr(port, "set_buffer_size"):
                port.set_buffer_size(rx_size=16384)
            port.dtr = True
            print(f"Opened {port.port} at line coding {args.baudrate}; "
                  f"warming up for {args.warmup:g} s.", flush=True)
            return measure(port, args)
    except (serial.SerialException, OSError, ValueError) as error:
        print(f"Serial error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
