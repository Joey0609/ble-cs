# CS radio-test client

> **Work in progress:** transport builds and radio behavior still need
> validation on the target hardware. Radio Test is disabled in the desktop
> application and this firmware is not part of the deployment flow.

Standalone host-link firmware for Nordic radio-test modes. It accepts the
radio-test configuration and control commands defined by
`common/libs/cs_protocol/README.md`, then runs them through the NCS
`radio_test` driver. Its supported-mode mask contains only radio test. The
Bluetooth CS client remains a separate application because the radio-test
driver directly owns RADIO and TIMER resources that conflict with Bluetooth
and MPSL.

## Build

Select the protocol transport at build time with Zephyr `FILE_SUFFIX`:

| Transport | Build command | Host link | Diagnostics |
| --- | --- | --- | --- |
| USB | `west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_radio_test_client -- -DFILE_SUFFIX=usb` | Native USB CDC ACM | uart20, 921600 baud |
| Debug UART | `west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_radio_test_client -- -DFILE_SUFFIX=debug_uart` | uart20, 921600 baud | Disabled on the protocol UART to preserve the binary stream |

The debug-UART transport has no DTR. The host ends the session with
`CLOSE_SESSION`; if the host disappears without that command, the session and
any running test remain active until the next host attaches or sends `STOP`.

Both configurations share `radio_test.conf` and `common.conf`. They use the
same radio-test session and state handlers as the radio-test build of
`cs_client`, so protocol configuration validation, finite-test completion,
RX statistics and stop behavior stay aligned with that implementation.

## Hardware notes

The USB build expects the board's native USB connector. The debug-UART build
uses uart20 at 921600 baud and requires the board's UART routing/debug adapter
to expose that instance. The driver bypasses Bluetooth and MPSL; a successful
build does not verify RF behavior on hardware.
