"""Bluetooth discovery and explicit peer selection."""
from PyQt6 import QtCore, QtWidgets as W


class PeerComboBox(W.QComboBox):
    """Keep scan updates out of the list while its popup is being used."""

    def hidePopup(self):
        super().hidePopup()
        if self._popup_closed is not None:
            # Let QComboBox finish committing the user's popup selection first.
            QtCore.QTimer.singleShot(0, self._popup_closed)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_closed = None


class PeersView(W.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.peers = PeerComboBox()
        self.peers._popup_closed = self._apply_pending_refresh
        self._pending_refresh = None
        self.peers.setMinimumContentsLength(40)
        self.peers.setToolTip("Advertised name · address / type · RSSI; peers whose name starts with a "
                              "scan prefix, or every peer with Show all")
        self.show_all = W.QCheckBox("Show all")
        self.show_all.setToolTip("List every scanned peer, including unnamed peers and names "
                                 "outside the scan prefixes; unnamed peers appear by address")
        self.advertise = W.QPushButton("Advertise")
        for widget in (self.peers, self.show_all, self.advertise):
            layout.addWidget(widget)
        layout.addStretch(1)

    def refresh(self, peers, replace=False):
        """Add newly discovered peers, or rebuild when the visibility filter changes."""
        if self.peers.view().isVisible():
            # Keep the open menu stable. Coalesce rapid scan results into the
            # newest snapshot, then apply it as soon as the user closes it.
            if self._pending_refresh is not None:
                replace = replace or self._pending_refresh[1]
            self._pending_refresh = (dict(peers), replace)
            return
        self._refresh_now(peers, replace)

    def clear(self):
        self._pending_refresh = None
        self.peers.clear()

    def _apply_pending_refresh(self):
        if self._pending_refresh is None:
            return
        peers, replace = self._pending_refresh
        self._pending_refresh = None
        self._refresh_now(peers, replace)

    def _refresh_now(self, peers, replace):
        selected = self.peers.currentData()
        existing = {self.peers.itemData(index) for index in range(self.peers.count())}
        if replace:
            self.peers.clear()
            existing.clear()
        for key, peer in peers.items():
            if key in existing:
                continue
            kind = "random" if peer.address_type else "public"
            suffix = "" if peer.flags & 1 else " · not connectable"
            self.peers.addItem(f"{peer.peer_name or '(unnamed)'} · {peer.address_text} / {kind} · {peer.rssi_dbm} dBm{suffix}", key)
            existing.add(key)
        if selected is not None:
            index = self.peers.findData(selected)
            if index >= 0:
                self.peers.setCurrentIndex(index)
