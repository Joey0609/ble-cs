import tempfile
import unittest
from pathlib import Path
import h5py
from scipy.io import loadmat
from cs_app.recorder import RunRecorder, load, read_description, update_description
from cs_app.session_history import HostMessage
from cs_app.h5_to_mat import convert
from cs_app.session import ClientSession
from cs_app.simulator import Simulator
from cs_app.protocol.config import ClientConfig
from cs_app.protocol.packets import PeripheralPatternsPacket, LogMessagePacket, CsFaeTablePacket, PacketType, ProtocolStatus, \
    CsProceduresCompletePacket, LogConfigPacket, CsPeerDataPacket, ConnectionParametersPacket
from cs_app.planner.bridge import config_packet
from cs_app.planner.model import Scenario
from cs_app.results import load_capture


def config():
    return ClientConfig(0, config_packet(Scenario()), PeripheralPatternsPacket.from_patterns(["CS"]))


def logged_config():
    return ClientConfig(0, config_packet(Scenario()), PeripheralPatternsPacket.from_patterns(["CS"]),
                        log=LogConfigPacket(4, 3))


class RecorderTests(unittest.TestCase):
    def test_connection_parameters_record_includes_mtu(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            recorder = RunRecorder(path, write_config=False)
            recorder.record(ConnectionParametersPacket(14, 0, 400, 498))
            recorder.close()
            with h5py.File(path) as file:
                report = file["reports/connection_parameters"]
                self.assertIn("mtu", report.dtype.names)
                self.assertEqual(report[0]["mtu"], 498)

    def test_description_can_be_written_and_edited_after_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            recorder = RunRecorder(path, config=config(), description="before")
            recorder.close()
            self.assertEqual(read_description(path), "before")
            update_description(path, "after\nnotes")
            self.assertEqual(read_description(path), "after\nnotes")
            with h5py.File(path) as file:
                self.assertTrue(file.attrs["description_updated"])

    def test_peer_data_in_config_reports_and_mat(self):
        from dataclasses import replace
        scenario = Scenario()
        scenario = replace(scenario, configuration=replace(scenario.configuration, cs_enhancements_1=1))
        initiator_only = ClientConfig(0, config_packet(scenario), PeripheralPatternsPacket.from_patterns(["CS"]),
                                      None, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            recorder = RunRecorder(path, config=initiator_only)
            recorder.record(CsPeerDataPacket(1))
            recorder.close()
            with h5py.File(path) as file:
                self.assertEqual(int(file["config/peer_data"][()]), 1)
                self.assertEqual(list(file["reports/peer_data"]["peer_data"]), [1])
            mat = loadmat(convert(path), simplify_cells=True)
            self.assertEqual(mat["config"]["peer_data"], 1)
            self.assertEqual(mat["reports"]["peer_data"]["peer_data"], 1)
            ras = Path(directory) / "ras.h5"
            RunRecorder(ras, config=config()).close()
            with h5py.File(ras) as file:
                self.assertEqual(int(file["config/peer_data"][()]), 0)

    def test_config_records_the_preferred_t_pm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            RunRecorder(path, config=ClientConfig(0, config_packet(Scenario()),
                                                  PeripheralPatternsPacket.from_patterns(["CS"]), t_pm=40)).close()
            with h5py.File(path) as file:
                self.assertEqual(int(file["config/t_pm"][()]), 40)
                # The payloads replay the SET_T_PM frame the client was sent.
                self.assertIn(bytes([40]), [bytes(row) for row in file["config/payloads"][:]])
            self.assertEqual(loadmat(convert(path), simplify_cells=True)["config"]["t_pm"], 40)
            default = Path(directory) / "default.h5"
            RunRecorder(default, config=config()).close()
            with h5py.File(default) as file:
                self.assertEqual(int(file["config/t_pm"][()]), 10)

    def test_config_records_log_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            recorder = RunRecorder(path, config=logged_config())
            recorder.record(LogMessagePacket(b"<inf> test: hello"))
            recorder.close()
            with h5py.File(path) as file:
                self.assertEqual(list(file["config/log"][:]), [4, 3])
                self.assertEqual(file["config/log"].attrs["console_level"], 4)
                self.assertEqual(file["config/log"].attrs["host_level"], 3)

    def test_host_log_round_trip_and_mat_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.h5"
            recorder = RunRecorder(path, write_config=False, clock=lambda: 10.0)
            recorder.record_host("warning", "host", "configuration refused", received_at=11.0)
            recorder.record_host("inf", "peer", "remote ready", received_at=12.0)
            recorder.close()
            with h5py.File(path) as file:
                self.assertEqual(list(file["host_log"]["level"]), [2, 3])
                self.assertEqual([value.decode() for value in file["host_log"]["source"]], ["host", "peer"])
            records = load(path, include_host=True, times=True, with_direction=True)
            self.assertEqual([record[1] for record in records],
                             [HostMessage("wrn", "host", "configuration refused"),
                              HostMessage("inf", "peer", "remote ready")])
            raw = loadmat(convert(path))["host_log"]
            # A 1x2 struct array with char rows, not a struct of columns with cell text.
            self.assertEqual(raw.shape, (1, 2))
            self.assertEqual(set(raw.dtype.names), {"timestamp", "level", "source", "text"})
            self.assertEqual(raw[0, 0]["text"].dtype.kind, "U")
            host_log = loadmat(convert(path, Path(directory) / "simple.mat"), simplify_cells=True)["host_log"]
            self.assertEqual([(r["timestamp"], r["level"], r["source"], r["text"]) for r in host_log],
                             [(1.0, 2, "host", "configuration refused"), (2.0, 3, "peer", "remote ready")])
            # A recording without host messages still has an empty host_log.
            empty = Path(directory) / "empty.h5"
            RunRecorder(empty, write_config=False).close()
            self.assertEqual(loadmat(convert(empty))["host_log"].shape, (1, 0))

    def test_context_replay_tones_and_mat(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.h5'
            packets = []
            sim = Simulator()
            s = ClientSession(emit=lambda event, value: packets.append(value) if event == 'packet_received' else None)
            s.set_host_config(config())
            s.connect(sim.transport)
            s.apply()
            s.start()
            sim.tick()
            s.stop()
            recorder = RunRecorder(path, config=config(), context=[Scenario().configuration, CsFaeTablePacket(0, 32)])
            packets += [LogMessagePacket(b'test log'), CsProceduresCompletePacket(7)]
            for packet in packets:
                recorder.record(packet)
            recorder.close('STOP confirmed')
            self.assertEqual([p.to_bytes() for p in load(path)], [p.to_bytes() for p in packets])
            self.assertEqual(len(load_capture(path.read_bytes())[0]), len(packets))
            with h5py.File(path) as file:
                self.assertEqual(file.attrs['close_reason'], 'STOP confirmed')
                self.assertIn('configuration', file['context'])
                self.assertEqual(file['context/fae'][0]['lsb_denominator'], 32)
                completion = [row for row in file['events'] if row['kind'] == b'CsProceduresCompletePacket']
                self.assertEqual([row['procedures_completed'] for row in completion], [7])
                for index, row in enumerate(file['results/subevents']):
                    steps = file['results/steps'][row['step_start']:row['step_start'] + row['num_steps']]
                    self.assertTrue(all(step['subevent_row'] == index for step in steps))
                for index, row in enumerate(file['results/steps']):
                    tones = file['results/tones'][row['tone_start']:row['tone_start'] + row['num_tones']]
                    self.assertTrue(all(tone['step_row'] == index for tone in tones))
            mat = loadmat(convert(path), simplify_cells=True)
            self.assertNotIn('raw', mat)
            self.assertEqual(mat['meta']['close_reason'], 'STOP confirmed')
            self.assertIn('procedure_counter', mat['results']['subevents'])

    def test_run_boundaries_rejected_start_partial_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            s = ClientSession()
            sim = Simulator()
            s.set_host_config(config())
            s.connect(sim.transport)
            s.apply()
            def factory(session, partial):
                path = Path(directory) / f'run{len(paths)}.h5'
                paths.append(path)
                return RunRecorder(path, config=config(), partial=partial)
            s.logging_factory = factory
            for i in range(2):
                s.start()
                sim.tick()
                s.stop()
            self.assertTrue(all(p.exists() for p in paths))
            original = sim.handle
            sim.handle = lambda p: sim.response(p, ProtocolStatus.REJECTED) if p.PACKET_TYPE == PacketType.START else original(p)
            s.start()
            self.assertFalse(paths[-1].exists())
            sim.handle = original
            s.logging_factory = None
            s.start()
            s.logging_factory = factory
            s.record_from_now()
            s.stop()
            with h5py.File(paths[-1]) as file:
                self.assertTrue(file.attrs['partial'])

    def test_reader_thread_timestamps_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [10.]
            path = Path(directory) / 'run.h5'
            recorder = RunRecorder(path, config=config(), clock=lambda: now[0])
            now[0] = 20.  # the GUI handles the frames late
            recorder.record(LogMessagePacket(b'late'), received_at=11.5)
            recorder.record(LogMessagePacket(b'buffered'), received_at=9.)
            recorder.record(LogMessagePacket(b'unstamped'))
            recorder.close()
            with h5py.File(path) as file:
                self.assertEqual(list(file['raw/frames']['t_host']), [1.5, 0., 10.])

    def test_existing_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.h5'
            path.write_bytes(b'keep')
            with self.assertRaises(OSError):
                RunRecorder(path, config=config())
            self.assertEqual(path.read_bytes(), b'keep')
