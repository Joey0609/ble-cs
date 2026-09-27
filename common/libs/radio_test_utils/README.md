# Radio test mode

`radio_test_mode` drives the NCS radio test driver through plain C settings,
so callers do not include Zephyr, nrfx or driver headers. It owns the driver
configuration and the HFXO request, and is meant for switching the radio
between roles (carrier, modulated TX, RX, sweeps) at runtime.

| Function | Purpose |
|----------|---------|
| `radio_test_mode_config_init()` | Fill caller-owned settings with defaults for a role. No hardware access. |
| `radio_test_mode_init()` | Start the crystal clock and initialize the driver. Call once. |
| `radio_test_mode_apply()` | Validate settings and make them the active role. Stops a running role first. |
| `radio_test_mode_start()` | Start the applied role. |
| `radio_test_mode_stop()` | Stop immediately, truncating any packet in the air. |
| `radio_test_mode_is_running()` | Whether a role is running. |
| `radio_test_mode_rx_stats_get()` | RX / RX sweep counts since start (CRC valid, CRC failed) and the latest packet's RSSI and channel. |

The driver only counts CRC-valid packets, restarts that count on every sweep
channel and takes no RSSI. `radio_test_mode_init()` therefore chains handlers in
front of the driver's radio and sweep timer interrupts (through the dynamic
software ISR table): once the driver enables RX, they also enable the CRCERROR
interrupt and the ADDRESS→RSSISTART shortcut, and count both outcomes.

```c
#include <radio_test_utils/radio_test_mode.h>

struct radio_test_mode_config role;
int err = radio_test_mode_init();

/* Transmit a carrier on 2403 MHz. */
err = radio_test_mode_config_init(&role, RADIO_TEST_MODE_UNMODULATED_TX);
role.channel = 3;
err = radio_test_mode_apply(&role);
err = radio_test_mode_start();

/* Switch to receiving on 2440 MHz. */
err = radio_test_mode_config_init(&role, RADIO_TEST_MODE_RX);
role.phy = RADIO_TEST_MODE_PHY_BLE_2M;
role.channel = 40;
err = radio_test_mode_apply(&role);
err = radio_test_mode_start();
```

Defaults: BLE 1M, channel 3, 0 dBm, random pattern, unlimited packets, sweep
0-80 with 10 ms dwell, 50% duty cycle, and 100 us transmit/sleep times. The
adapter also supports constant `00000000` and `11111111` payload/address
patterns; it applies those after the NCS driver's standard radio setup.
Settings are copied by `apply`, so the caller's structure need not outlive it.

`apply` returns `-EINVAL` for out-of-range channels (0-80, or 11-26 for
IEEE 802.15.4), an inverted or zero-dwell sweep, a duty cycle outside 1-99,
or zero sleep-sweep times, and `-ENOTSUP` for a PHY the SoC lacks. On error the
current role is left untouched. Transmit power values the SoC does not support
fall back to 0 dBm inside the driver. Sleep sweeps use the driver's own channel
sequence, not the start/end range.

With a non-zero `packet_count`, MODULATED_TX, RX and MODULATED_TX_DUTY_CYCLE
stop by themselves; `radio_test_mode_is_running()` then turns false and the
optional `done_cb` runs from interrupt or system work queue context. The API is
not thread-safe: call it from a single thread.

Set `APP_LIBS_RADIO_TEST` to `ON`, include `common/libs/libs.cmake` after
Zephyr setup, and link `app_libs` to the application. Compile the NCS sample's
`radio_test.c` separately, as shown in `tests/radio_test/CMakeLists.txt`.

`libs.cmake` requires `CONFIG_CRC=y` for the shared protocol library,
`CONFIG_FEM_AL_LIB=y` for the driver headers (even on boards without a FEM)
and `CONFIG_CLOCK_CONTROL_NRF=y` for the crystal clock. With `CONFIG_FEM=y`, a
supported MPSL FEM backend and FEM-only MPSL mode are required; the `fem`
settings are ignored otherwise. Bluetooth and full MPSL are rejected because
they own the same radio resources. The consuming application supplies the
driver Kconfig (see `tests/radio_test/prj.conf`).
