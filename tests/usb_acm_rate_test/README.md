# USB CDC ACM throughput test

This directory is a standalone Zephyr application. It produces one 1024-byte
burst every 10 ms while the host asserts DTR, using a repeating binary 0..255
pattern. The nominal average is 102,400 bytes/s (0.1024 MB/s); this workload
does not measure the maximum achievable USB throughput. Partial FIFO writes
are retried from the correct position. If the previous burst has not yet been
fully queued at the next tick, that new burst is skipped. Missed producer ticks
are also skipped instead of being sent as a catch-up burst. The debugger-visible
`usb_rate_skipped_bursts` counter records these skips while DTR is asserted.
Bluetooth is disabled. `printk` output is redirected into Zephyr's deferred
logging system with a 256-byte queue. The logging thread sends buffered output
through the asynchronous UART backend, using a 256-byte transmit buffer and
UARTE DMA on the board's debug UART (`uart20`, 921600 baud), accessible through
the debugger's serial port. The backend flushes after each message or when its
transmit buffer fills; normal output does not use per-character UART polling.
Zephyr falls back to polling in panic mode or if asynchronous backend
initialization fails. Queued messages can be dropped if logging cannot keep up.
The native USB CDC interface carries only the test byte stream and keeps its
interrupt-driven API. Logging still has CPU and scheduling overhead, so this
measures USB reception with debug output enabled, not CS processing.

Build from the repository root with an activated Nordic SDK environment:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp -d usb_acm_rate_test/build usb_acm_rate_test
west flash -d usb_acm_rate_test/build
```

Connect the board's native USB data port, close other serial readers, and run:

```sh
python3 -m pip install pyserial
python3 usb_acm_rate_test/main_usb_acm_receiver_rate_tester.py /dev/cu.usbmodem1302 --duration 30
```

Replace the port with the enumerated device. Find ports with
`python3 -m serial.tools.list_ports`. The baud setting defaults to 115200 and
does not throttle native CDC transfers; `--baudrate 10000000` can test alternate
line coding if the macOS driver accepts it.

The receiver discards a two-second warmup, reads 16 KiB chunks, and reports
interval and cumulative average throughput. The final average divides all bytes
received during measurement by elapsed monotonic wall time, including read
timeouts and reporting overhead. A read can overrun the requested duration by
approximately its 100 ms timeout plus scheduling overhead; the actual elapsed
time is used. Ctrl-C prints partial results once measurement has started.
MB/s means 1,000,000 bytes/s. This benchmark counts bytes without parsing,
displaying payloads, writing them to disk, or verifying their integrity.

The TX FIFO is 8 KiB in `app.overlay`. Change the FIFO size and rebuild to
compare sizes. The producer retains at most one additional 1 KiB burst awaiting
FIFO space. USB and host buffering can combine bursts into larger reads; the
receiver measures average bytes per second, not individual burst timing.
The installed NCS v3.4.0 CDC implementation does not expose upstream's newer
`CONFIG_USBD_CDC_ACM_BUF_POOL_SIZE`; this test uses its supported dedicated
buffer pool and workqueue settings. In this SDK the dedicated transfer buffers
are fixed to the maximum bulk packet size (512 bytes in a high-speed build).
Buffer size alone does not guarantee 4 MB/s.
For that target, confirm macOS System Information reports a 480 Mb/s USB link.
