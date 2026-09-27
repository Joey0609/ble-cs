import unittest

from ble_channel_sounding.peer_console import PeerConsoleReader


class PeerConsoleTests(unittest.TestCase):
    def test_lines_and_levels_survive_chunk_boundaries(self):
        lines = []
        reader = PeerConsoleReader(lambda level, text, timestamp: lines.append((level, text, timestamp)))
        reader.feed(b"<err> first\r\nplain", 1.0)
        reader.feed(b" line\n<dbg> last\n", 2.0)
        reader.flush(2.0)
        self.assertEqual(lines, [("err", "first", 1.0), ("inf", "plain line", 2.0),
                                 ("dbg", "last", 2.0)])

    def test_flushes_unterminated_line(self):
        lines = []
        reader = PeerConsoleReader(lambda level, text, timestamp: lines.append((level, text, timestamp)))
        reader.feed(b"<wrn> disconnected")
        reader.flush(3.0)
        self.assertEqual(lines, [("wrn", "disconnected", 3.0)])

    def test_hexdump_continuations_join_the_previous_line(self):
        lines = []
        reader = PeerConsoleReader(lambda level, text, timestamp: lines.append((level, text, timestamp)))
        reader.feed(b"<err> HCI event\n 01 02 03 04\n 05 06 07 08\nnext\n", 4.0)
        reader.flush(4.0)
        self.assertEqual(lines, [("err", "HCI event 01 02 03 04 05 06 07 08", 4.0),
                                 ("inf", "next", 4.0)])

    def test_levels_follow_the_firmware_timestamp_prefix(self):
        lines = []
        reader = PeerConsoleReader(lambda level, text, timestamp: lines.append((level, text)))
        # app_log_console.c prints "[s.ms] <lvl> module: text"; Zephyr prints "[hh:mm:ss.ms,us] <lvl> ...".
        reader.feed(b"[13.102] <err> cs_reflector_tag: TEST FAIL remote CS capabilities\r\n"
                    b"[00:00:13.102,622] <wrn> bt_hci_core: opcode 0x208a status 0x2f\r\n"
                    b"[00:00:00.014,963] <inf> bt_sdc_hci_driver: build revision:\r\n"
                    b"                    e4 43 46 f0 19 ef 4f ca  92 99 81 90 a7 9d 08 97 |.CF...O. ........\r\n"
                    b"*** Booting nRF Connect SDK ***\r\n")
        reader.flush()
        self.assertEqual(lines, [
            ("err", "[13.102] cs_reflector_tag: TEST FAIL remote CS capabilities"),
            ("wrn", "[00:00:13.102,622] bt_hci_core: opcode 0x208a status 0x2f"),
            ("inf", "[00:00:00.014,963] bt_sdc_hci_driver: build revision: e4 43 46 f0 19 ef 4f ca  "
                    "92 99 81 90 a7 9d 08 97 |.CF...O. ........"),
            ("inf", "*** Booting nRF Connect SDK ***")])


if __name__ == "__main__":
    unittest.main()
