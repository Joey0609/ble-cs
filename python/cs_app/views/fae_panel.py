"""FAE plot with per-report scale and link provenance."""
from PyQt6 import QtWidgets as W
import pyqtgraph as pg
from ..protocol.packets import CapabilitiesSource
from ..fae import FAE_CHANNELS, FaeTable


class FaePanel(W.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = FaeTable.zeros()
        self.link_number = 0
        self.report_time = None
        self.previous_link = False
        self.reflector = False
        self.remote_no_fae_supported = None
        self.ipt_enabled = None
        layout = W.QVBoxLayout(self)
        self.info = W.QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.plot = pg.PlotWidget(background="white")
        self.plot.setLabel("bottom", "CS channel")
        self.plot.setLabel("left", "FAE", units="ppm")
        self.curve = self.plot.plot(pen="#2a78d6", symbol="o", symbolSize=3)
        layout.addWidget(self.plot)
        self.refresh()

    def set_reflector(self, reflector):
        self.reflector = reflector
        self.refresh()

    def observe_capabilities(self, packet):
        """Remember the remote No_FAE capability for the current link."""
        if packet.source == CapabilitiesSource.REMOTE:
            self.remote_no_fae_supported = bool(packet.cs_without_fae_supported)
            self.refresh()

    def observe_configuration(self, packet):
        """Remember whether the controller actually enabled IPT."""
        self.ipt_enabled = bool(packet.cs_enhancements_1 & 0x01)
        self.refresh()

    def mark_previous_link(self):
        self.previous_link = True
        self.remote_no_fae_supported = None
        self.ipt_enabled = None
        self.refresh()

    def clear(self):
        """Forget the FAE report from the previous host session."""
        self.table = FaeTable.zeros()
        self.link_number = 0
        self.report_time = None
        self.previous_link = False
        self.remote_no_fae_supported = None
        self.ipt_enabled = None
        self.refresh()

    def add_packet(self, packet, *, link_number=0, timestamp=None):
        try:
            table = FaeTable.from_packet(packet)
        except ValueError as error:
            self.info.setText(f"{error}; keeping previous table")
            return False
        self.table, self.link_number, self.report_time = table, link_number, timestamp
        self.previous_link = False
        self.refresh()
        return True

    def refresh(self):
        self.curve.setData(FAE_CHANNELS, self.table.ppm())
        stats = self.table.stats()
        if self.report_time is None and self.remote_no_fae_supported:
            if self.ipt_enabled:
                fae_status = ("No remote FAE table expected: the peer supports FAE-less CS "
                               "and IPT is enabled.")
            else:
                fae_status = "No remote FAE table expected: the peer supports FAE-less CS."
        elif self.report_time is None and self.ipt_enabled:
            fae_status = ("IPT is enabled; a remote FAE table is still applicable unless the "
                          "peer advertises FAE-less CS.")
        else:
            fae_status = "No FAE report yet"
        self.info.setText(
            ("FAE is reported by the initiator only. " if self.reflector else "") +
            ("Previous link · " if self.previous_link else "") +
            f"Link {self.link_number} · " +
            (fae_status if self.report_time is None else f"Report time {self.report_time}") +
            f" · mean {stats.mean_ppm:+.5f} ppm · std {stats.std_ppm:.5f} ppm"
            f" · range {stats.min_ppm:+.5f} to {stats.max_ppm:+.5f} ppm"
            f" · scale {self.table.ppm_per_lsb:g} ppm/LSB")
