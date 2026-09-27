# B205mini radio test packet transmitter

Open the packet transmitter in GNU Radio Companion:

```sh
gnuradio-companion scripts/b205mini_radio_test_tx.grc
```

Connect the B205mini, use its `TX/RX` port, then press **Run**. The flowgraph
transmits a repeating BLE 1M GFSK packet stream at 4 MS/s, centered at
2403 MHz (Nordic radio-test channel 3). It uses the `11001100` pattern, a
matching five-byte `0xCC` address, and the 254-byte repeated payload used by
this workspace's `radio_test` modulated-TX configuration. TX gain starts at
0 dB; adjust it in the UHD Sink block for a cabled or shielded test setup.

Configure the receiving Nordic radio-test device for **RX**, **BLE 1M**,
channel **3**, and pattern **11001100**. The receiver's address pattern must
match the transmitter. The radio-test frame uses no CRC, matching the Nordic
`radio_test` sample configuration.

The prior spectrum capture remains available as
`scripts/b205mini_2403_spectrum.grc`.
