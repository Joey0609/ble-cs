import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cs_app.protocol.packets import (CsInitiatorSubeventResultPacket, CsReflectorSubeventResultPacket,
                                     LogMessagePacket)
from cs_app.session_history import HostMessage, SessionHistory
from cs_app.session import ClientSession


class _Transport:
    def __init__(self, error=None):
        self.error = error
        self.on_data = lambda data: None
        self.on_error = lambda error: None
        self.is_open = False

    def open(self):
        if self.error:
            raise OSError(self.error)
        self.is_open = True

    def close(self):
        self.is_open = False


class SessionHistoryTests(unittest.TestCase):
    def test_context_and_directions_round_trip(self):
        history = SessionHistory([LogMessagePacket(b"context")], segment_bytes=128)
        try:
            history.append(LogMessagePacket(b"received"), timestamp=1.25)
            history.append(LogMessagePacket(b"sent"), timestamp=1.5, direction="sent")
            self.assertEqual(
                [(timestamp, packet.message, direction) for timestamp, packet, direction in history.iter_packets()],
                [(0.0, b"context", "received"), (1.25, b"received", "received"),
                 (1.5, b"sent", "sent")],
            )
        finally:
            history.close()

    def test_oldest_segments_are_dropped_and_index_remains_readable(self):
        one = LogMessagePacket(b"one")
        history = SessionHistory(max_bytes=2 * (len(one.to_bytes()) + 32),
                                 segment_bytes=len(one.to_bytes()))
        try:
            for number in range(4):
                history.append(LogMessagePacket(str(number).encode()), timestamp=float(number))
            entries = history.snapshot()
            self.assertTrue(history.truncated)
            self.assertEqual([history.read(entry).message for entry in entries], [b"2", b"3"])
            self.assertEqual(history.first_kept_timestamp, 2.0)
            self.assertEqual([entry.index for entry in entries], [2, 3])
        finally:
            history.close()

    def test_procedure_summaries_count_reports_per_procedure_and_resume(self):
        def subevent(cls, counter):
            return cls(0, 10 + counter, counter, 0, 0, 0, 0, 0, 0, 1, 0, ())

        history = SessionHistory()
        try:
            for counter in range(3):
                history.append(subevent(CsInitiatorSubeventResultPacket, counter), timestamp=float(counter))
                history.append(LogMessagePacket(b"between"), timestamp=float(counter))
                history.append(subevent(CsReflectorSubeventResultPacket, counter), timestamp=float(counter),
                               direction="sent")
            summaries, highest, lowest = history.procedure_summaries()
            self.assertEqual([summary.key for summary in summaries],
                             [(0, 10, 0), (0, 11, 1), (0, 12, 2)])
            self.assertEqual([(summary.initiator, summary.reflector) for summary in summaries],
                             [(1, 1)] * 3)
            self.assertEqual((highest, lowest), (8, 0))

            # Resuming after the last scanned record reports only what is new.
            history.append(subevent(CsReflectorSubeventResultPacket, 2), timestamp=3.0)
            history.append(subevent(CsInitiatorSubeventResultPacket, 3), timestamp=3.0)
            summaries, highest, lowest = history.procedure_summaries(after=highest)
            self.assertEqual([(summary.key, summary.initiator, summary.reflector) for summary in summaries],
                             [((0, 12, 2), 0, 1), ((0, 13, 3), 1, 0)])
            self.assertEqual((highest, lowest), (10, 0))
        finally:
            history.close()

    def test_procedure_summaries_report_the_oldest_record_the_history_still_holds(self):
        def subevent(counter):
            return CsInitiatorSubeventResultPacket(0, 10 + counter, counter, 0, 0, 0, 0, 0, 0, 1, 0, ())

        size = len(subevent(0).to_bytes())
        history = SessionHistory(max_bytes=2 * (size + 32), segment_bytes=size)
        try:
            for counter in range(4):
                history.append(subevent(counter), timestamp=float(counter))
            summaries, highest, lowest = history.procedure_summaries()
            self.assertTrue(history.truncated)
            self.assertEqual([summary.key for summary in summaries], [(0, 12, 2), (0, 13, 3)])
            self.assertEqual((highest, lowest), (3, 2))
        finally:
            history.close()

    def test_live_tail_is_bounded_while_full_index_stays_on_disk(self):
        history = SessionHistory(segment_bytes=1024 * 1024)
        try:
            for number in range(1500):
                history.append(LogMessagePacket(str(number).encode()), timestamp=float(number))
            history.flush()
            self.assertEqual(len(history.entries), 200)
            self.assertEqual([entry.index for entry in history.snapshot(limit=2)], [1498, 1499])
            self.assertEqual(sum(1 for _ in history.iter_entries()), 1500)
        finally:
            history.close(discard=True)

    def test_close_discard_clears_entries(self):
        history = SessionHistory()
        history.append(LogMessagePacket(b"data"))
        history.close(discard=True)
        self.assertEqual(history.entries, [])

    def test_flush_after_close_does_not_wait_on_stopped_writer(self):
        history = SessionHistory()
        history.close()
        history.flush(timeout=0.01)

    def test_flush_reports_writer_failure_instead_of_timeout(self):
        history = SessionHistory()
        history._write = lambda item: (_ for _ in ()).throw(OSError("disk full"))
        history.append(LogMessagePacket(b"will fail"))
        try:
            with self.assertRaisesRegex(OSError, "disk full"):
                history.flush()
        finally:
            try:
                history.close(discard=True)
            except OSError:
                pass

    def test_hostless_open_failure_does_not_replace_previous_history(self):
        events = []
        session = ClientSession(emit=lambda event, value: events.append((event, value)))
        previous = SessionHistory()
        previous.append(LogMessagePacket(b"previous"))
        session.history = previous
        session.connect_hostless(_Transport("cannot open"))
        self.assertIs(session.history, previous)
        self.assertFalse(any(event == "session_started" for event, _ in events))
        previous.close()

    def test_hostless_open_and_disconnect_bound_one_history(self):
        events = []
        session = ClientSession(emit=lambda event, value: events.append((event, value)))
        session.connect_hostless(_Transport())
        history = session.history
        self.assertIsNotNone(history)
        self.assertEqual([event for event, _ in events][:2], ["session_started", "history_started"])
        session.close()
        history.close()

    def test_save_replays_both_directions_and_cancel_removes_partial_file(self):
        from cs_app.recorder import load

        history = SessionHistory()
        try:
            history.append(LogMessagePacket(b"rx"), timestamp=1.0)
            history.append(LogMessagePacket(b"tx"), timestamp=2.0, direction="sent")
            with TemporaryDirectory() as directory:
                path = Path(directory) / "session.h5"
                history.save_hdf5(path, write_config=False)
                self.assertEqual([packet.message for packet in load(path, include_tx=True)], [b"rx", b"tx"])
                cancelled = Path(directory) / "cancelled.h5"
                with self.assertRaises(InterruptedError):
                    history.save_hdf5(cancelled, write_config=False, cancel=lambda: True)
                self.assertFalse(cancelled.exists())
        finally:
            history.close()

    def test_host_records_round_trip_and_save_to_hdf5(self):
        from cs_app.recorder import load

        history = SessionHistory()
        try:
            history.append(LogMessagePacket(b"frame"), timestamp=1.0)
            history.append_host("warning", "host", "START refused", timestamp=1.5)
            history.append_host("inf", "peer", "peer online", timestamp=2.0)
            entries = history.snapshot()
            self.assertEqual([entry.kind for entry in entries], ["log", "host", "peer"])
            self.assertEqual(history.read(entries[1]), HostMessage("wrn", "host", "START refused"))
            self.assertEqual([(timestamp, type(value), direction) for timestamp, value, direction in history.iter_records()],
                             [(1.0, LogMessagePacket, "received"),
                              (1.5, HostMessage, "host"),
                              (2.0, HostMessage, "host")])
            with TemporaryDirectory() as directory:
                path = Path(directory) / "session.h5"
                history.save_hdf5(path, write_config=False)
                records = load(path, include_host=True, times=True, with_direction=True)
                self.assertEqual([record[1] for record in records[1:]],
                                 [HostMessage("wrn", "host", "START refused"),
                                  HostMessage("inf", "peer", "peer online")])
        finally:
            history.close()

    def test_client_disables_history_after_writer_failure(self):
        history = SessionHistory()
        history._write = lambda item: (_ for _ in ()).throw(OSError("disk full"))
        history.append(LogMessagePacket(b"will fail"))
        try:
            history.flush()
        except OSError:
            pass
        events = []
        session = ClientSession(emit=lambda event, value: events.append((event, value)))
        session.history = history
        session.tick()
        self.assertIsNone(session.history)
        self.assertTrue(any(event == "history_error" and "disk full" in value for event, value in events))


if __name__ == "__main__":
    unittest.main()
