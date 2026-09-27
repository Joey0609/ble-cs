"""Host-side validation of radio settings, peripheral name prefixes and antennas.

The radio rules mirror common/libs/radio_test_utils/radio_test_mode.c, the local
antenna rules host_link_config_check_antennas() in common/libs/host_link/host_link_config.h
and the preferred peer antenna rule cs_*_config_set_procedure() in common/libs/cs_utils/cs_config.c.
Hardware-specific PHY and TX power support is still decided by the device.
"""
from .protocol.packets import (CsInitiatorConfigPacket, CsReflectorConfigPacket, PeripheralPatternsPacket,
                                 RadioTestPattern, RadioTestPhy, RadioTestType, RadioTxTestConfigPacket)

T = RadioTestType
CHANNEL_TESTS = (T.UNMODULATED_TX, T.MODULATED_TX, T.RX, T.MODULATED_TX_DUTY_CYCLE)
SWEEP_TESTS = (T.TX_SWEEP, T.RX_SWEEP)
SLEEP_TESTS = (T.TX_SWEEP_WITH_SLEEP, T.TX_SWEEP_WITH_SLEEP_MODULATED)
SYNC_ANTENNA_REPETITIVE, SYNC_ANTENNA_NO_RECOMMENDATION = 0xFE, 0xFF
# (initiator antennas, reflector antennas) per tone_antenna_config_selection.
TONE_ANTENNA_COUNTS = ((1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (1, 3), (1, 4), (2, 2))


def validate_antennas(config, num_antennas: int) -> list[str]:
    """Antenna selections of a CS configuration packet that exceed the client's local antennas.

    Only the client's own side is checked: A of the tone antenna configuration for an
    initiator, B for a reflector, and a named CS_SYNC antenna. The peer's side is left to
    the controller. Returns an empty list for radio test configurations.
    """
    if not isinstance(config, (CsInitiatorConfigPacket, CsReflectorConfigPacket)):
        return []
    errors = []
    sync = config.cs_sync_antenna_selection
    if not (1 <= sync <= 4 or sync in (SYNC_ANTENNA_REPETITIVE, SYNC_ANTENNA_NO_RECOMMENDATION)):
        errors.append(f"Unknown CS_SYNC antenna selection 0x{sync:02x}")
    elif sync <= 4 and sync > num_antennas:
        errors.append(f"CS_SYNC antenna {sync} is not available: the client has {num_antennas} "
                      f"{'antenna' if num_antennas == 1 else 'antennas'}")
    selection = config.tone_antenna_config_selection
    if not 0 <= selection < len(TONE_ANTENNA_COUNTS):
        errors.append(f"Unknown antenna configuration {selection}")
    else:
        initiator = isinstance(config, CsInitiatorConfigPacket)
        needed = TONE_ANTENNA_COUNTS[selection][0 if initiator else 1]
        if needed > num_antennas:
            a, b = TONE_ANTENNA_COUNTS[selection]
            errors.append(f"Antenna configuration A{a}:B{b} needs {needed} "
                          f"{'initiator' if initiator else 'reflector'} antennas; the client has {num_antennas} "
                          f"{'antenna' if num_antennas == 1 else 'antennas'}")
    return errors


def validate_preferred_peer_antenna(config) -> list[str]:
    """The preferred peer antenna mask of a CS configuration packet, as the firmware setters check it.

    The mask names peer antennas 1–4 (bits 0–3) and sets at least as many bits as the peer's
    side of the tone antenna configuration: B for an initiator, A for a reflector. Whether the
    peer has those antennas is known only from its capabilities (check_compatibility()).
    Returns an empty list for radio test configurations and unknown antenna configurations,
    which validate_antennas() reports.
    """
    if not isinstance(config, (CsInitiatorConfigPacket, CsReflectorConfigPacket)):
        return []
    mask, selection = config.preferred_peer_antenna, config.tone_antenna_config_selection
    if not 1 <= mask <= 0x0F:
        return [f"Preferred peer antenna 0x{mask:02x} must name peer antennas 1–4 (bit mask 1–15)"]
    if not 0 <= selection < len(TONE_ANTENNA_COUNTS):
        return []
    initiator = isinstance(config, CsInitiatorConfigPacket)
    a, b = TONE_ANTENNA_COUNTS[selection]
    needed, bits = (b if initiator else a), bin(mask).count("1")
    if bits < needed:
        return [f"Antenna configuration A{a}:B{b} uses {needed} {'reflector' if initiator else 'initiator'} "
                f"antennas; preferred peer antenna 0x{mask:02x} names {bits}. Set at least {needed} bits, "
                f"for example {(1 << needed) - 1}"]
    return []


def validate_patterns(patterns) -> list[str]:
    errors = []
    if isinstance(patterns, PeripheralPatternsPacket):
        p = patterns
        if not 1 <= p.count <= 8 or len(p.lengths) != 8 or len(p.patterns) != 256:
            return ["Peripheral patterns require 1–8 slots with 8 lengths and 256 data bytes"]
        for i, length in enumerate(p.lengths):
            slot = p.patterns[i * 32:(i + 1) * 32]
            if i >= p.count:
                if length or any(slot):
                    errors.append(f"Unused pattern slot {i + 1} must be zero")
                continue
            if not 1 <= length <= 32:
                errors.append(f"Pattern {i + 1} must be 1–32 UTF-8 bytes")
            if any(slot[length:]):
                errors.append(f"Pattern {i + 1} has nonzero padding")
            try:
                text = slot[:length].decode("utf-8")
                if "\0" in text:
                    errors.append(f"Pattern {i + 1} contains NUL")
            except UnicodeDecodeError:
                errors.append(f"Pattern {i + 1} is not UTF-8")
        return errors
    if not isinstance(patterns, (list, tuple)) or not 1 <= len(patterns) <= 8:
        return ["Supply 1–8 peripheral name prefixes"]
    for i, name in enumerate(patterns):
        try:
            if not isinstance(name, str) or not 1 <= len(name.encode("utf-8")) <= 32 or "\0" in name:
                errors.append(f"Pattern {i + 1} must be 1–32 UTF-8 bytes without NUL")
        except UnicodeEncodeError:
            errors.append(f"Pattern {i + 1} is not UTF-8")
    return errors


def validate_radio_test(config: RadioTxTestConfigPacket) -> list[str]:
    errors = []
    try:
        config.to_frame()
    except (ValueError, TypeError, OverflowError) as error:
        errors.append(str(error))
    if config.test_type not in set(RadioTestType):
        errors.append("Unknown radio test type")
    if config.phy not in set(RadioTestPhy):
        errors.append("Unknown radio PHY")
    if config.pattern not in set(RadioTestPattern):
        errors.append("Unknown radio pattern")
    if config.test_type in CHANNEL_TESTS:
        low, high = (11, 26) if config.phy == RadioTestPhy.IEEE802154_250K else (0, 80)
        if not low <= config.channel <= high:
            errors.append(f"Channel must be {low}–{high} for this PHY")
    if config.test_type in SWEEP_TESTS:
        # These modes sweep raw frequency offsets in the C helper, even for IEEE PHY.
        if not 0 <= config.sweep_start_channel <= config.sweep_end_channel <= 80:
            errors.append("Sweep channels must satisfy 0 ≤ start ≤ end ≤ 80")
        if config.sweep_delay_ms <= 0:
            errors.append("Sweep dwell must be positive")
    if config.test_type == T.MODULATED_TX_DUTY_CYCLE and not 1 <= config.duty_cycle <= 99:
        errors.append("Duty cycle must be 1–99 percent")
    if config.test_type in SLEEP_TESTS and (config.tx_time_us <= 0 or config.sleep_time_us <= 0):
        errors.append("Transmit and sleep times must be positive")
    return errors
