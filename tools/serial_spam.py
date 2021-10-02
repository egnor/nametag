#!/usr/bin/env python3

import argparse
import time

import serial  # type: ignore

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyACM0")
parser.add_argument("--baud", type=int, default=115200)
parser.add_argument("--bps", type=float, default=1000000)
parser.add_argument("--chunk", type=int, default=128)

args = parser.parse_args()

with serial.Serial(args.port, baudrate=args.baud, timeout=0) as serial:
    start_mono = time.monotonic()
    rx_total = tx_total = 0
    next_status = 0.0
    while True:
        elapsed = time.monotonic() - start_mono
        if elapsed > next_status:
            print(
                f"tx={tx_total}b/{elapsed:.1f}s={tx_total/elapsed:.1f}bps "
                f"| rx={rx_total}b/{elapsed:.1f}s={rx_total/elapsed:.1f}bps"
            )
            next_status += 1.0
            continue

        rx_total += len(serial.read(serial.in_waiting) or b"")
        delay = ((tx_total + args.chunk) / args.bps) - elapsed
        if delay < 0:
            tx_total += serial.write(b"x" * args.chunk)
        else:
            time.sleep(min(1, delay))
