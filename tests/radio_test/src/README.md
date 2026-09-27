# Radio test driver application

> **Work in progress:** this direct-radio test image is experimental and is
> not part of the supported deployment flow. The desktop app's Radio Test mode
> is disabled.

Drives the NCS radio test driver (`radio_test.c`) directly from a compiled-in
configuration, instead of through the sample's interactive shell.

`radio_test.c` is compiled straight out of the NCS tree
(`$ZEPHYR_NRF_MODULE_DIR/samples/peripheral/radio_test/src`) by
[CMakeLists.txt](../CMakeLists.txt), so there is no forked copy to keep in sync.
Only the sample's shell front-end (`radio_cmd.c`) is left out.

## Configuring a test

Edit the `TEST_*` block at the top of [radio_test_cfg.c](radio_test_cfg.c),
then rebuild and flash. The selected `TEST_MODE` decides which of the other
macros apply; the rest are ignored.

The application uses the shared [radio test mode API](../../../common/libs/radio_test_utils/README.md),
which starts the crystal clock, initializes the driver, applies these settings
and starts the test.

`TEST_CHANNEL` is a radio frequency index, not a BLE channel index:
`f = 2400 + TEST_CHANNEL` MHz.

## Building

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp -d radio_test/build radio_test
west flash -d radio_test/build
```

## Constraint: cannot coexist with Bluetooth

The driver takes `RADIO`, `TIMER10` and `EGU10` directly. MPSL reserves the same
peripherals on the nRF54L series, so this application is a separate image from
the Bluetooth applications — the two cannot run on one device at the same time. A
`BUILD_ASSERT` in [main.c](main.c) rejects any build with `CONFIG_BT` enabled.
