"""Qt-free, single-command host session with injectable deadlines."""
from collections import deque
from dataclasses import replace
import time
from .protocol import PROTOCOL_VERSION
from .protocol.config import ClientConfig
from .protocol.packets import (
    ScanStartPacket, AdvertiseStartPacket, PeerConnectPacket, ScanResultPacket,
    PacketType, ProtocolStatus, ClientState, ConnectPacket, ConnectResponsePacket,
    CommandResponsePacket, ClientStatePacket, RasDataLostPacket, CsProceduresCompletePacket, GetConfigPacket,
    OperationMode, OperationModePacket, CsInitiatorConfigPacket, CsReflectorConfigPacket,
    RadioTxTestConfigPacket, PeripheralPatternsPacket, DeviceNamePacket, ApplyConfigPacket,
    PeerDataPacket, LogConfigPacket, TpmPacket, CsPeerDataPacket, StartPacket, StopPacket, LinkDisconnectPacket, CloseSessionPacket,
    ConnectionParametersPacket, RejectReason, error_name,
)
from .protocol.receiver import PacketReceiver
from .config_sync import field_diff, sync_state
from .session_history import SessionHistory
from .validation import validate_antennas, validate_patterns, validate_preferred_peer_antenna, validate_radio_test

TIMEOUTS = {kind: 2.0 for kind in PacketType}
TIMEOUTS[PacketType.CONNECT] = 10.0
for _kind in (PacketType.STOP, PacketType.LINK_DISCONNECT, PacketType.APPLY_CONFIG,
              PacketType.START, PacketType.GET_CONFIG):
    TIMEOUTS[_kind] = 5.0
LINK_ACTIVE = {ClientState.LINK_CONNECTING, ClientState.SCANNING, ClientState.ADVERTISING, ClientState.LINK_CONNECTED,
               ClientState.RAS_READY, ClientState.RUNNING, ClientState.STOPPED}
def interruption_text(packet, *, earlier=False):
    """Message for a CLIENT_STATE that reports an interrupted or failed operation."""
    try:
        state = ClientState(packet.state).name
    except ValueError:
        state = f"state {packet.state}"
    text = (f"Client operation {'was ' if earlier else ''}interrupted: {state}, "
            f"reason {RejectReason(packet.reason).name if packet.reason in RejectReason._value2member_map_ else packet.reason}, "
            f"error {error_name(packet.error)} ({packet.error})")
    if packet.hci_status:
        text += f", HCI status 0x{packet.hci_status:02x}"
    return text


def command_rejection_text(request, packet):
    """Human-readable command rejection including every diagnostic from the client."""
    reason = RejectReason(packet.reason).name if packet.reason in RejectReason._value2member_map_ else packet.reason
    return (f"{request.PACKET_TYPE.name} rejected: status {packet.status}, "
            f"reason {reason}, error {error_name(packet.error)} ({packet.error})")


NOT_SYNCED ="Cannot start: the configuration is not synced with the client. Apply or synchronise the configuration first."
CONFIG_PACKETS = (OperationModePacket, CsInitiatorConfigPacket, CsReflectorConfigPacket,
                  RadioTxTestConfigPacket, PeripheralPatternsPacket, DeviceNamePacket, PeerDataPacket, TpmPacket,
                  LogConfigPacket)


class ClientSession:
    def __init__(self, *, clock=time.monotonic, emit=None, history_factory=SessionHistory,
                 history_kwargs=None):
        self.clock = clock
        self.emit = emit or (lambda event, value: None)
        self.state = "DISCONNECTED"
        self.link_state = ClientState.IDLE
        self.host_config = None
        self.client_config = None
        self.client_valid = False
        self.client_crc = 0
        self.info = None
        self.transport = None
        self.pending = None
        self.queue = deque()
        self.receiver = PacketReceiver()
        self.recorder = None
        self.logging_factory = None
        self.context = {}
        self.frames = 0
        self.packet_errors = 0
        self.ras_lost = 0
        # Set by CS_PROCEDURES_COMPLETE, which ends the run before its CLIENT_STATE(STOPPED, TEST_COMPLETE).
        self.procedures_completed = None
        self.received_config = []
        self.applying = None
        self.peers = {}
        self.hostless = False
        # CONNECT_RESPONSE reported a run this session did not start; GET_CONFIG is pending.
        self.attached_to_run = False
        self.history = None
        self.pending_history = None
        # Hosted receive history is opened only after CONNECT_RESPONSE.  A
        # hostless stream has no handshake and is ready as soon as its UART
        # transport opens.
        self.connect_confirmed = False
        # A session toggle closes the port once CLOSE_SESSION is confirmed;
        # Disconnect link ends the same session and leaves the port open (§7.8).
        self._close_port_with_session = False
        self.history_factory = history_factory
        self.history_kwargs = dict(history_kwargs or {})

    @property
    def in_sync(self):
        if self.hostless:
            # Hostless firmware owns its configuration and emits reports; it
            # has no host-side configuration to synchronise or compare.
            return True
        return sync_state(self.host_config, self.client_valid, self.client_crc) == "in sync"

    @property
    def applied_peer_data(self):
        """Reflector data of the client's applied configuration, or None when the host does not know it.

        cs_client sends CS_PEER_DATA only at configuration complete, once per link, so a
        host that reconnects to an established link learns the setting only from here.
        """
        config = self.client_config
        if config is None or not self.client_valid or config.crc32() != self.client_crc:
            return None
        return config.peer_data if config.mode == OperationMode.CS_INITIATOR else 0

    @property
    def can_disconnect_link(self):
        """Whether LINK_DISCONNECT has anything to do.

        The frame stops discovery as well as an established link, and the
        firmware accepts it without one, answering LINK_DISCONNECTED.  A radio
        test reports RUNNING with no link at all, so the applied operation mode
        decides as well as the client state.
        """
        mode = self.client_config.mode if self.client_config else None
        return (self.link_state not in (ClientState.IDLE, ClientState.LINK_DISCONNECTED)
                and mode != OperationMode.RADIO_TX_TEST)

    @property
    def running(self):
        """A run is starting, active or stopping; the configuration is locked until it ends."""
        return (self.state in ("STARTING", "RUNNING", "STOPPING") or
                (self.transport is not None and self.link_state == ClientState.RUNNING))

    def _state(self, state):
        self.state = state
        self.emit("state_changed", state)

    def set_host_config(self, config):
        self.host_config = config
        self.emit("sync_changed", self.in_sync)

    def _discard_history(self, history, *, discard=True):
        if history is None:
            return
        try:
            history.close(discard=discard)
        except (OSError, ValueError) as error:
            self.emit("history_error", str(error))

    def _new_history(self):
        try:
            # ``context`` also carries scalar application state such as peer_data;
            # only protocol packets can seed the raw-frame history.
            context = (value for value in self.context.values()
                       if hasattr(value, "to_bytes") and hasattr(value, "PACKET_TYPE"))
            return self.history_factory(context, **self.history_kwargs)
        except Exception as error:
            # History is diagnostic storage. A failure must not prevent the radio
            # session from running or stop an already-running client.
            self.emit("history_error", str(error))
            return None

    def _record_history(self, packet, *, direction="received", received_at=None):
        history = self.pending_history or self.history
        if history is None:
            return
        if history.error is not None:
            self._disable_history(history)
            return
        try:
            history.append(packet, timestamp=self.clock() if received_at is None else received_at,
                           direction=direction)
        except (OSError, ValueError) as error:
            if history is self.pending_history:
                self.pending_history = None
                self._discard_history(history)
            else:
                self.history = None
                self._discard_history(history)
            self.emit("history_error", str(error))

    def record_host(self, level, source, text, timestamp=None):
        """Record a host/peer message without affecting command or run state."""
        timestamp = self.clock() if timestamp is None else timestamp
        history = self.pending_history or self.history
        if history is not None:
            if history.error is not None:
                self._disable_history(history)
            else:
                try:
                    history.append_host(level, source, text, timestamp=timestamp)
                except (OSError, ValueError) as error:
                    self._disable_history(history)
                    self.emit("history_error", str(error))
        if self.recorder is not None:
            try:
                self.recorder.record_host(level, source, text, received_at=timestamp)
            except (OSError, ValueError) as error:
                # A diagnostic record must never interrupt the radio run.
                self.emit("history_error", f"recording host log disabled: {error}")

    def _disable_history(self, history):
        if history is self.pending_history:
            self.pending_history = None
        if history is self.history:
            self.history = None
        message = str(history.error or "history is unavailable")
        try:
            history.close(discard=True)
        except (OSError, ValueError):
            pass
        self.emit("history_error", message)

    def _commit_pending_history(self):
        history = self.pending_history
        self.pending_history = None
        if history is None:
            return
        if self.history is not None and self.history is not history:
            self._discard_history(self.history)
        self.history = history
        self.emit("history_started", history)

    def _reset_session(self):
        """Clear the per-session state a new handshake starts from.

        Shared by the first connection over a port and by a reconnection over
        a port a session close left open (§7.8).
        """
        self.connect_confirmed = False
        self.receiver = PacketReceiver()
        self.info = None
        self.peers.clear()
        self.link_state = ClientState.IDLE
        self.client_config = None
        self.client_valid = False
        self.attached_to_run = False
        self.applying = None
        self.context.clear()
        self.frames = 0
        self.packet_errors = 0
        self.ras_lost = 0
        self.procedures_completed = None
        self.received_config = []
        self.queue.clear()
        self.pending = None
        self._close_port_with_session = False

    def connect(self, transport, *, hostless=False):
        if self.transport is not None:
            raise ValueError("Close the current session first")
        # A fresh hosted connection is a new session boundary. Hostless open
        # is special: preserve the previous Results/history until open() has
        # actually succeeded.
        self._discard_history(self.pending_history)
        self.pending_history = None
        if not hostless:
            self._discard_history(self.history)
            self.history = None
        self.transport = transport
        self.hostless = hostless
        self._reset_session()
        self.connect_confirmed = bool(hostless)
        transport.on_data, transport.on_error = self.feed, self.fail
        if hostless:
            # Do not clear the previous Results view until open() succeeds.
            # The temporary history may receive the first frames during open.
            self.pending_history = self._new_history()
            try:
                transport.open()
                self.emit("session_started", None)
                self._commit_pending_history()
                self._state("HOSTLESS CS")
            except Exception as error:
                self._discard_history(self.pending_history)
                self.pending_history = None
                self.fail(str(error))
            return
        self.emit("session_started", None)
        self._state("CONNECTING")
        try:
            transport.open()
            self._send(ConnectPacket(PROTOCOL_VERSION))
        except Exception as error:
            self.fail(str(error))

    def connect_hostless(self, transport):
        """Open a hostless device as a receive-only protocol stream.

        Hostless firmware starts operating at boot and never implements the
        hosted client's CONNECT/COMMAND transaction.
        """
        self.connect(transport, hostless=True)

    def reconnect(self):
        """Start a new host session over a port a session close left open (§7.8).

        Disconnect link ends the session without closing the port, so the next
        Connect is a fresh CONNECT handshake rather than a port open.  The
        client keeps its applied configuration across host sessions, which the
        handshake re-syncs.
        """
        if self.transport is None or self.hostless:
            raise ValueError("No open port to connect over")
        if self.state != "DISCONNECTED":
            raise ValueError("Close the current session first")
        self._discard_history(self.pending_history)
        self.pending_history = None
        self._discard_history(self.history)
        self.history = None
        self._reset_session()
        self.emit("session_started", None)
        self._state("CONNECTING")
        self._send(ConnectPacket(PROTOCOL_VERSION))

    def _send(self, packet):
        if self.hostless:
            raise RuntimeError("Hostless CS is receive-only")
        if self.pending:
            raise RuntimeError("A command is already pending")
        wire = packet.to_bytes()
        if self.info and len(wire) > self.info.max_frame_size:
            self.fail("Command exceeds client maximum frame size")
            return
        self.pending = (packet, self.clock() + TIMEOUTS[packet.PACKET_TYPE])
        self.emit("packet_sent", packet)
        self._record_history(packet, direction="sent")
        try:
            if self.recorder:
                self.recorder.record(packet, direction="tx")
            self.transport.write(wire)
        except Exception as error:
            self.fail(str(error))

    def _next(self):
        if self.queue and self.pending is None and self.transport is not None:
            self._send(self.queue.popleft())

    def _idle(self):
        if self.transport is None or self.pending or self.queue or self.state in ("CONNECTING", "FAILED", "DISCONNECTED"):
            raise ValueError("Session is not ready for another command")

    def fetch_config(self):
        self._idle()
        self.received_config = []
        self._state("SYNCING" if self.state != "RUNNING" else "RUNNING")
        self._send(GetConfigPacket())

    def apply(self, *, allow_interrupt=False):
        self._idle()
        if self.host_config is None:
            raise ValueError("No host configuration")
        config = self.host_config
        errors = validate_radio_test(config.config) if isinstance(config.config, RadioTxTestConfigPacket) else []
        if hasattr(config.config, "gap_role") and config.config.gap_role == 0:
            errors += validate_patterns(config.patterns if config.patterns else [])
        errors += validate_preferred_peer_antenna(config.config)
        if self.info:
            errors += validate_antennas(config.config, self.info.num_antennas_supported)
        if errors:
            raise ValueError("\n".join(errors))
        if self.info and not self.info.supported_modes & (1 << config.mode):
            raise ValueError("Client does not support this operation mode")
        if self.running:
            raise ValueError("The configuration cannot be changed while running; stop the run first")
        active = self.link_state in LINK_ACTIVE
        if active and not allow_interrupt:
            raise ValueError("Applying disconnects the Bluetooth link")
        # A host session can end while the firmware keeps its Bluetooth peer
        # link. On reconnect, the host's cached link state may not reflect that
        # retained link yet. Always clear it before applying CS configuration;
        # LINK_DISCONNECT is idempotent when no peer is connected and does not
        # close the host session. Radio-to-radio applies have no Bluetooth link.
        previous_mode = (self.client_config.mode if self.client_config else
                         self.info.operation_mode if self.info and self.info.config_valid else None)
        cs_mode = config.mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR)
        previous_cs_mode = previous_mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR)
        disconnect_before_apply = active or cs_mode or previous_cs_mode
        self.applying = config
        self.queue.extend(([LinkDisconnectPacket()] if disconnect_before_apply else []) +
                          config.packets() + [ApplyConfigPacket()])
        self._state("SYNCING")
        self._next()

    def _discovery_ready(self, role):
        self._idle()
        if self.running or not self.in_sync:
            raise ValueError("Apply or synchronise the configuration before discovery")
        if getattr(self.host_config.config, "gap_role", None) != role:
            raise ValueError("Discovery command does not match the configured GAP role")
        if self.link_state in LINK_ACTIVE and self.link_state != ClientState.SCANNING:
            raise ValueError("Disconnect the current Bluetooth link first")

    def scan(self):
        self._discovery_ready(0)
        if self.link_state == ClientState.SCANNING:
            raise ValueError("Scanning is already active")
        self.peers.clear()
        self._send(ScanStartPacket())

    def visible_peers(self, show_all=False):
        """Scan results to list: peers whose name starts with an applied prefix, or all.

        The firmware reports every peer; the prefixes filter here. Names compare as
        bytes, like the firmware's own match, and an unnamed peer stays hidden until
        a scan response names it. Without prefixes every peer is listed.
        """
        patterns = self.host_config.patterns if self.host_config else None
        if show_all or patterns is None:
            return dict(self.peers)
        prefixes = [name.encode() for name in patterns.names()]
        return {key: peer for key, peer in self.peers.items()
                if any(peer.name[:peer.name_length].startswith(prefix) for prefix in prefixes)}

    def advertise(self):
        self._discovery_ready(1)
        self._send(AdvertiseStartPacket())

    def connect_peer(self, key):
        self._discovery_ready(0)
        if key not in self.peers:
            raise ValueError("Select a discovered peer")
        peer = self.peers[key]
        if not peer.flags & 1:
            raise ValueError("The selected peer is not connectable")
        self._send(PeerConnectPacket(peer.address_type, peer.address))

    def start(self):
        self._idle()
        if self.running:
            raise ValueError("A run is already active")
        if not self.in_sync:
            raise ValueError(NOT_SYNCED)
        self.procedures_completed = None
        if self.logging_factory:
            self.recorder = self.logging_factory(self, False)
        # START is the first frame of a prospective run. It is kept in a
        # pending history until the client confirms the command; a refusal
        # therefore cannot replace the previous completed session.
        self.pending_history = self._new_history()
        self._state("STARTING")
        self._send(StartPacket(self.host_config.crc32()))

    def record_from_now(self):
        if self.state != "RUNNING" or self.recorder or not self.logging_factory:
            raise ValueError("No unrecorded running session")
        if self.client_config is None and not self.in_sync:
            raise ValueError("Fetch the running configuration before recording")
        self.recorder = self.logging_factory(self, True)
        self.emit("run_started", "partial")

    def stop(self):
        self._idle()
        self._state("STOPPING")
        self._send(StopPacket())

    def disconnect_link(self):
        """Disconnect the Bluetooth link and end the host session; the port stays open.

        A session whose peer is gone has nothing left to measure (§7.8), so
        LINK_DISCONNECT is followed by CLOSE_SESSION.  No STOP precedes either:
        the client stops itself on both.
        """
        self.close_session()

    def cancel_connect(self):
        """Abandon a CONNECT the client has not answered yet.

        The handshake has no transaction ID, so a cancelled attempt cannot be
        resumed: the transport is closed exactly as a CONNECT timeout closes
        it, but the session ends DISCONNECTED because nothing went wrong.
        """
        if self.state != "CONNECTING":
            raise ValueError("No connection attempt to cancel")
        self.pending = None
        self.connect_confirmed = False
        self.queue.clear()
        self._close_port_with_session = False
        self._discard_history(self.pending_history)
        self.pending_history = None
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        self._state("DISCONNECTED")

    def close_session(self, *, close_port=False):
        """End the host session: LINK_DISCONNECT, then CLOSE_SESSION (§7.8).

        STOP is never queued first.  For a running measurement STOP and
        CLOSE_SESSION are the same operation in the firmware, and
        ``link_disconnect()`` stops the client itself, so both frames end a run
        on their own.
        """
        self._idle()
        self._close_port_with_session = close_port
        if self.can_disconnect_link:
            self.queue.append(LinkDisconnectPacket())
        self.queue.append(CloseSessionPacket())
        if self.running:
            self._state("STOPPING")
        self._next()

    def close_port(self):
        """Close the serial port, ending whatever session it carried."""
        self._finish_run("session closed")
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        self.hostless = False
        self.connect_confirmed = False
        self._close_port_with_session = False
        self.pending = None
        self.queue.clear()
        self._state("DISCONNECTED")

    def close(self):
        """The session toggle: end the session and close the port.

        Hostless mode has no command channel, so there the toggle only closes
        the port, and so does a port a previous session close left open.
        """
        if self.hostless or self.state == "DISCONNECTED":
            self.close_port()
            return
        self.close_session(close_port=True)

    def _finish_run(self, reason, *, discard=False):
        if self.recorder:
            recorder, self.recorder = self.recorder, None
            recorder.close(reason, discard=discard)
            if discard:
                self.emit("recording_discarded", recorder.path)
        self.emit("run_finished", reason)

    def fail(self, reason):
        self.pending = None
        self.connect_confirmed = False
        self.queue.clear()
        self.applying = None
        self._close_port_with_session = False
        self._discard_history(self.pending_history)
        self.pending_history = None
        try:
            self._finish_run("transport loss: " + str(reason))
        except OSError as error:
            self.emit("link_error", str(error))
        if self.transport:
            self.transport.close()
            self.transport = None
        self.hostless = False
        self._state("FAILED")
        self.emit("link_error", str(reason))

    def tick(self):
        for history in (self.pending_history, self.history):
            if history is not None and history.error is not None:
                self._disable_history(history)
        if self.hostless:
            # A hostless device has no command transaction or handshake
            # deadline. It remains connected while report frames arrive.
            self.pending = None
            return
        if self.pending and self.clock() >= self.pending[1]:
            kind = self.pending[0].PACKET_TYPE
            # Without a transaction ID a late reply can match a later command.
            # Close the transport on timeout; never reuse an ambiguous session.
            self.fail(f"{kind.name} timeout")

    def feed(self, data, received_at=None):
        """Decode received bytes; received_at is the time.monotonic() read time, when known."""
        previous_errors = self.receiver.frames.invalid_frames
        packets = self.receiver.feed(data)
        self.packet_errors += len(self.receiver.packet_errors) + self.receiver.frames.invalid_frames - previous_errors
        self.receiver.packet_errors.clear()
        for packet in packets:
            self.receive(packet, received_at)

    def receive(self, packet, received_at=None):
        self.frames += 1
        name = type(packet).__name__
        if self.hostless and self.recorder is None and self.logging_factory:
            # Hostless images start without a host configuration. Begin a
            # partial stream recording when the first protocol frame arrives.
            self.recorder = self.logging_factory(self, True)
            self.emit("run_started", "partial")
        if name in ("CsCapabilitiesPacket", "CsConfigurationPacket", "CsProcedureEnableCompletePacket", "CsFaeTablePacket"):
            # Capabilities are kept per source (local/remote), the others per configuration ID.
            self.context[(name, getattr(packet, "id", getattr(packet, "config_id", getattr(packet, "source", 0))))] = packet
        # Ignore hosted receive frames that arrive before the handshake.  The
        # ConnectResponse itself is the boundary event and is allowed through;
        # hostless CS has no response and is ready from transport open.
        if self.connect_confirmed or self.hostless or isinstance(packet, ConnectResponsePacket):
            self._record_history(packet, received_at=received_at)
        if self.recorder:
            try:
                self.recorder.record(packet, received_at=received_at)
            except OSError as error:
                self.fail(str(error))
                return
        if isinstance(packet, ScanResultPacket):
            key = (packet.address_type, packet.address)
            old = self.peers.get(key)
            if old:
                keep_name = old.name_length and (not packet.name_length or (old.flags & 2 and not packet.flags & 2))
                packet = replace(packet, flags=((packet.flags | old.flags) & 1) | (old.flags & 2 if keep_name else packet.flags & 2),
                                 name=old.name if keep_name else packet.name,
                                 name_length=old.name_length if keep_name else packet.name_length)
            self.peers[key] = packet
        self.last_received_at = self.clock() if received_at is None else received_at
        self.emit("packet_received", packet)
        if isinstance(packet, RasDataLostPacket):
            self.ras_lost += 1
        if isinstance(packet, CsPeerDataPacket):
            self.context["peer_data"] = packet.peer_data
            self.emit("peer_data", packet.peer_data)
        if isinstance(packet, ConnectionParametersPacket):
            self.context["connection_parameters"] = packet
            self.emit("connection_parameters", packet)
        if isinstance(packet, CsProceduresCompletePacket):
            self.procedures_completed = packet.procedures_completed
            self.emit("procedures_complete", packet.procedures_completed)
            self._finish_run(f"complete: {packet.procedures_completed} procedures")
            if self.pending is None:
                self._state("CONFIGURED" if self.client_valid else "CONNECTED")
            return
        if isinstance(packet, ClientStatePacket):
            was_running = self.running
            link_ended_run = False
            self.link_state = packet.state
            self.emit("link_state_changed", packet.state)
            self.emit("client_state", packet)
            if packet.state == ClientState.RUNNING and self.pending is None and not self.queue:
                self._state("RUNNING")
            if packet.state in (ClientState.LINK_LOST, ClientState.LINK_DISCONNECTED):
                self.context.clear()
                # A lost Bluetooth link ends the current run even when the
                # firmware cannot deliver a command response.  Leave the
                # host session usable so its configuration can be edited or
                # applied again after the link is gone.
                if was_running or self.recorder:
                    self._finish_run("client state: " + ClientState(packet.state).name)
                    link_ended_run = True
                # A spontaneous link-loss report supersedes an outstanding
                # command.  Preserve the normal LINK_DISCONNECT transaction
                # so an apply sequence can continue after its response.
                if self.pending and not isinstance(self.pending[0], LinkDisconnectPacket):
                    self.pending = None
                    self.queue.clear()
                    self.applying = None
                if self.pending is None and not self.queue:
                    self._state("CONFIGURED" if self.client_valid else "CONNECTED")
            interrupted = packet.reason == RejectReason.INTERRUPTED or packet.error != 0
            if interrupted:
                # Also arrives right after CONNECT_RESPONSE for an interruption the client could not deliver.
                self.emit("link_error", interruption_text(packet, earlier=not was_running))
            stopping = bool(self.pending) and isinstance(self.pending[0], StopPacket)  # the STOP response closes the run
            completed = packet.reason == RejectReason.TEST_COMPLETE and packet.state == ClientState.STOPPED
            if completed and self.procedures_completed is not None:
                # CS_PROCEDURES_COMPLETE already ended this run.
                self.procedures_completed = None
                return
            if packet.state in (ClientState.ERROR, ClientState.LINK_LOST) or completed \
                    or (interrupted and was_running and not stopping):
                if not link_ended_run:
                    self._finish_run("client state: " + ClientState(packet.state).name +
                                     (f" ({error_name(packet.error)})" if packet.error else ""))
                if self.pending is None:
                    self._state("CONFIGURED" if self.client_valid else "CONNECTED")
            return
        if isinstance(packet, CONFIG_PACKETS) and self.pending and isinstance(self.pending[0], GetConfigPacket):
            self.received_config.append(packet)
            return
        if isinstance(packet, ConnectResponsePacket):
            if not self.pending or not isinstance(self.pending[0], ConnectPacket):
                return
            if packet.status != ProtocolStatus.OK or packet.protocol_version != PROTOCOL_VERSION:
                self.fail(f"Connect rejected: status {packet.status}, version {packet.protocol_version}")
                return
            self.pending = None
            self.connect_confirmed = True
            self.info = packet
            self.client_valid, self.client_crc = bool(packet.config_valid), packet.config_crc32
            self.link_state = packet.client_state
            self._state("RUNNING" if packet.client_state == ClientState.RUNNING else
                        "CONFIGURED" if self.client_valid else "CONNECTED")
            self.emit("client_info", packet)
            self.emit("sync_changed", self.in_sync)
            if packet.client_state == ClientState.RUNNING and not self.hostless:
                # Only a client without DTR (hardware UART) runs on without a host; a USB CDC
                # client stops when its host goes away. Learn what this run uses.
                self.attached_to_run = True
                self.received_config = []
                self._send(GetConfigPacket())
            return
        if not isinstance(packet, CommandResponsePacket) or not self.pending:
            return
        request = self.pending[0]
        if packet.request_type != request.PACKET_TYPE:
            self.fail("Unexpected command response")
            return
        self.pending = None
        self.emit("command_result", packet)
        if packet.status != ProtocolStatus.OK:
            applying = self.applying is not None
            self.queue.clear()
            self.applying = None
            if isinstance(request, StartPacket):
                self._discard_history(self.pending_history)
                self.pending_history = None
                self._finish_run("START rejected", discard=True)
            if isinstance(request, StopPacket):
                self._finish_run("STOP rejected")
            self.client_crc = packet.config_crc32
            self._state("RUNNING" if self.link_state == ClientState.RUNNING else "CONFIGURED" if self.client_valid else "CONNECTED")
            if isinstance(request, StartPacket) and packet.status == ProtocolStatus.CONFIG_MISMATCH:
                self.emit("start_failed", NOT_SYNCED)
            else:
                self.emit("sync_failed" if applying else "link_error",
                          command_rejection_text(request, packet))
            self.emit("sync_changed", self.in_sync)
            return
        if isinstance(request, StartPacket) and packet.config_crc32 != request.config_crc32:
            # The client confirmed START with a configuration other than the host's: never run or record it.
            self.client_crc = packet.config_crc32
            self._discard_history(self.pending_history)
            self.pending_history = None
            self._finish_run("START configuration mismatch", discard=True)
            self.link_state = ClientState.RUNNING
            self._state("STOPPING")
            self._send(StopPacket())
            self.emit("sync_changed", self.in_sync)
            self.emit("start_failed", NOT_SYNCED + f"\n\nClient configuration CRC 0x{packet.config_crc32:08x}, "
                                                  f"host configuration CRC 0x{request.config_crc32:08x}.")
            return
        if isinstance(request, GetConfigPacket):
            try:
                config = ClientConfig.from_packets(self.received_config)
                if config.crc32() != packet.config_crc32:
                    raise ValueError("GET_CONFIG CRC mismatch")
            except ValueError as error:
                self.fail(str(error))
                return
            self.client_config = config
            self.client_valid, self.client_crc = True, packet.config_crc32
            self.emit("config_received", config)
            if self.attached_to_run:
                self.attached_to_run = False
                # Differences from the host's own configuration, before the app replaces it.
                self.emit("attached_to_run", {"config": config, "differences":
                          field_diff(self.host_config, config) if self.host_config else None})
            self._state("RUNNING" if self.link_state == ClientState.RUNNING else "CONFIGURED")
        elif isinstance(request, ApplyConfigPacket):
            if packet.config_crc32 != self.applying.crc32():
                self.fail("APPLY_CONFIG CRC mismatch")
                return
            self.client_config = self.applying
            self.applying = None
            self.client_valid, self.client_crc = True, packet.config_crc32
            self._state("CONFIGURED")
        elif isinstance(request, StartPacket):
            self._commit_pending_history()
            self.link_state = ClientState.RUNNING
            self._state("RUNNING")
            self.emit("run_started", "started")
        elif isinstance(request, StopPacket):
            if self.link_state != ClientState.LINK_DISCONNECTED:
                self.link_state = ClientState.STOPPED
            self._finish_run("STOP confirmed")
            self._state("SYNCING" if self.queue else "CONFIGURED")
        elif isinstance(request, LinkDisconnectPacket):
            self.link_state = ClientState.LINK_DISCONNECTED
            self.context.clear()
            if not self.queue:
                self._state("CONFIGURED" if self.client_valid else "CONNECTED")
        elif isinstance(request, CloseSessionPacket):
            self._finish_run("session closed")
            self.connect_confirmed = False
            if self._close_port_with_session:
                self._close_port_with_session = False
                self.transport.close()
                self.transport = None
            self._state("DISCONNECTED")
        self.emit("sync_changed", self.in_sync)
        self._next()
