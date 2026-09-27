from __future__ import annotations

import unittest

from cs_app.fae import (
    FAE_CHANNELS,
    FAE_TABLE_ENTRIES,
    FaeTable,
    channel_frequency_mhz,
)


class ChannelMapTests(unittest.TestCase):
    def test_channels_skip_reserved(self) -> None:
        self.assertEqual(len(FAE_CHANNELS), FAE_TABLE_ENTRIES)
        self.assertEqual(len(set(FAE_CHANNELS)), FAE_TABLE_ENTRIES)
        self.assertEqual(FAE_CHANNELS[0], 2)
        self.assertEqual(FAE_CHANNELS[20], 22)
        self.assertEqual(FAE_CHANNELS[21], 26)
        self.assertEqual(FAE_CHANNELS[-1], 76)
        self.assertFalse({0, 1, 23, 24, 25, 77, 78, 79} & set(FAE_CHANNELS))


class FaeTableTests(unittest.TestCase):
    def test_rejects_bad_size_and_range(self) -> None:
        with self.assertRaises(ValueError):
            FaeTable((0,) * 71)
        with self.assertRaises(ValueError):
            FaeTable((128,) + (0,) * 71)

    def test_from_bytes_is_signed(self) -> None:
        table = FaeTable.from_bytes(bytes([0xFF, 0x80, 0x7F]) + bytes(69))
        self.assertEqual(table.entries[:3], (-1, -128, 127))

    def test_from_protocol_packet_keeps_packet_scale(self) -> None:
        from cs_app.protocol.frame import Frame
        from cs_app.protocol.packets import CsFaeTablePacket, decode_packet

        entries = (32, -16) + (0,) * 70
        wire = CsFaeTablePacket(hci_status=0, lsb_denominator=16, entries=entries).to_bytes()
        table = FaeTable.from_packet(decode_packet(Frame.from_bytes(wire)), "link 1")
        self.assertEqual(table.entries, entries)
        self.assertEqual(table.ppm()[:2], (2.0, -1.0))
        with self.assertRaises(ValueError):
            FaeTable.from_packet(CsFaeTablePacket(0x1F, 32))
        with self.assertRaises(ValueError):
            FaeTable.from_packet(CsFaeTablePacket(0, 0))

    def test_units(self) -> None:
        table = FaeTable((10,) * FAE_TABLE_ENTRIES)
        self.assertAlmostEqual(table.ppm(0.1)[0], 1.0)
        self.assertAlmostEqual(table.ppm(0.5)[0], 5.0)
        # 1 ppm at channel 2 (2404 MHz) is 2404 Hz.
        self.assertAlmostEqual(table.hz(0.1)[0], 2404.0)
        self.assertEqual(table.by_channel(0.1)[76], 1.0)

    def test_stats_constant_offset(self) -> None:
        stats = FaeTable((-15,) * FAE_TABLE_ENTRIES).stats(0.1)
        self.assertAlmostEqual(stats.mean_ppm, -1.5)
        self.assertAlmostEqual(stats.std_ppm, 0.0)
        self.assertAlmostEqual(stats.slope_ppm_per_mhz, 0.0)
        self.assertAlmostEqual(stats.fit_residual_rms_ppm, 0.0)

    def test_stats_linear_slope_and_extremes(self) -> None:
        # One LSB per MHz: the slope is exact and residual zero, gap included.
        entries = tuple(channel - 40 for channel in FAE_CHANNELS)
        stats = FaeTable(entries).stats(0.1)
        self.assertAlmostEqual(stats.slope_ppm_per_mhz, 0.1)
        self.assertAlmostEqual(stats.fit_residual_rms_ppm, 0.0, places=9)
        self.assertEqual((stats.min_channel, stats.max_channel), (2, 76))
        self.assertAlmostEqual(stats.min_ppm, -3.8)
        self.assertAlmostEqual(channel_frequency_mhz(40), 2442.0)



class PacketScaleTests(unittest.TestCase):
    def test_zero_fallback_and_packet_scale(self):
        from cs_app.protocol.packets import CsFaeTablePacket
        self.assertTrue(FaeTable.zeros().is_zero)
        self.assertEqual(FaeTable((32,) * 72).ppm()[0], 1)
        table = FaeTable.from_packet(CsFaeTablePacket(0, 16, (32,) * 72))
        self.assertEqual(table.ppm()[0], 2)
        self.assertEqual(table.stats().mean_ppm, 2)
        for packet in (CsFaeTablePacket(1, 32), CsFaeTablePacket(0, 0)):
            with self.assertRaises(ValueError):
                FaeTable.from_packet(packet)


if __name__ == "__main__":
    unittest.main()
