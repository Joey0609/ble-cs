# nRF54L15 Radio TX Packet Test

> **Work in progress:** this direct-radio test image is experimental and is
> not part of the supported deployment flow. The desktop app's Radio Test mode
> is disabled.

Standalone direct-radio transmitter for the nRF54L15. It sends Nordic
radio-test packets with a deterministic repeated payload/address bit pattern.
It does not start Bluetooth Channel Sounding. The project can run on the
`nrf54l15dk/nrf54l15/cpuapp` DK target.

## Select the transmitted contents

Edit `TEST_PATTERN` in [src/test_cfg.c](src/test_cfg.c), rebuild, and flash.
The four supported known-content choices are:

| Setting | Repeated bits |
| --- | --- |
| `RADIO_TEST_MODE_PATTERN_11110000` | `11110000` |
| `RADIO_TEST_MODE_PATTERN_11001100` | `11001100` |
| `RADIO_TEST_MODE_PATTERN_00000000` | `00000000` |
| `RADIO_TEST_MODE_PATTERN_11111111` | `11111111` |

The compile-time check rejects other patterns. `TEST_PHY`, `TEST_CHANNEL`,
`TEST_TXPOWER_DBM`, and `TEST_PACKET_COUNT` select the PHY, radio frequency
index, output power, and number of packets. A count of zero transmits
continuously. The radio channel is `2400 + TEST_CHANNEL` MHz.

The NCS `radio_test.c` driver is compiled directly from the installed SDK;
the shared `radio_test_mode` adapter applies the pattern after the driver's
standard packet setup. Pattern bytes apply to both the packet address and
payload. A SWD probe with an RTT viewer displays the active configuration.

## Build and flash

From an NCS terminal, build for the DK:

```sh
west build --no-sysbuild -b nrf54l15dk/nrf54l15/cpuapp \
  -d cs_tag_modulated_tx/build -p always cs_tag_modulated_tx
west flash -d cs_tag_modulated_tx/build
```

## Radio ownership

The NCS radio-test driver drives the radio and timing peripherals directly.
MPSL and Bluetooth use the same resources, so this image cannot run alongside
`cs_reflector_tag` or another Bluetooth application. Reset the board to stop
a continuous transmission. Use this only on an appropriately controlled test
setup and channel.
