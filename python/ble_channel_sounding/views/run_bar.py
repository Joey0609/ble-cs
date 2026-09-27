"""Session actions shown in the top-panel toolbar."""
from PyQt6 import QtCore, QtGui, QtWidgets as W
from . import icons

# Toolbar order; each tuple is a group separated from the next one.
GROUPS = (
    ("Connect",),
    ("Apply config", "Synchronise"),
    ("Scan", "Connect peer"),
    ("Start session", "Stop session"),
    # Record management: what the session keeps, and what the views show from disk.
    ("Record from now", "Describe session", "Open capture…", "Clear"),
    ("Help",),
)
ACTIONS = tuple(name for group in GROUPS for name in group)


class RunBar(W.QToolBar):
    """Movable session-action toolbar.

    ``buttons`` intentionally contains the tool buttons rather than the
    underlying actions. The application historically connected to these
    buttons directly, and keeping that interface also makes the toolbar
    convenient to exercise in GUI tests.
    """

    ICONS = {
        "Connect": "connect",
        "Apply config": "apply",
        "Synchronise": "sync",
        "Scan": "scan",
        "Connect peer": "link-connect",
        "Start session": "start",
        "Stop session": "stop",
        "Record from now": "record",
        "Describe session": "describe",
        "Open capture…": "open",
        "Clear": "clear",
        "Help": "help",
    }
    # Connect action by host-session state: label and icon.
    CONNECTION_STATES = {
        "disconnected": ("Connect client", "connect"),
        "connecting": ("Cancel connection", "cancel"),
        "connected": ("Disconnect client", "unplug"),
    }

    # Only actions whose name does not say enough on its own.
    TOOLTIPS = {
        "Scan": "Scan for nearby peers matching the configured name prefixes",
        "Connect peer": "Connect to the selected peer",
        "Describe session": "Describe session — notes kept with the session and written to its recording",
        "Open capture…": "Open capture… — show a recording or capture file in Results and the Session timeline",
        "Clear": "Clear — drop the shown results, the open capture and the session timeline",
        "Help": "Help — what CS Host does and how to use it: first steps, hardware, configuration, results and recordings",
    }

    def __init__(self, parent=None):
        super().__init__("Session actions", parent)
        self.setObjectName("sessionToolbar")
        self.setMovable(True)
        self.setFloatable(True)
        self.setAllowedAreas(QtCore.Qt.ToolBarArea.TopToolBarArea | QtCore.Qt.ToolBarArea.BottomToolBarArea)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QtCore.QSize(18, 18))
        self.buttons = {}
        self.toolbar_actions = {}
        self._connection_state = None
        for index, group in enumerate(GROUPS):
            if index:
                self.addSeparator()
            for name in group:
                self._add(name)

    def add_peer_controls(self, peers, show_all):
        """Place the discovery selector and filter beside Scan in the toolbar."""
        before = self.toolbar_actions["Connect peer"]
        peers.setMinimumContentsLength(28)
        peers.setMinimumWidth(280)
        self.insertWidget(before, peers)
        self.insertWidget(before, show_all)
        peers.setVisible(False)
        show_all.setVisible(False)

    def _add(self, name):
        tip = self.TOOLTIPS.get(name, name)
        action = QtGui.QAction(icons.icon(self.ICONS[name]), name, self)
        action.setToolTip(tip)
        action.setStatusTip(tip)
        self.addAction(action)
        button = self.widgetForAction(action)
        button.setToolTip(tip)
        self.buttons[name] = button
        self.toolbar_actions[name] = action

    def set_connection_state(self, connected, connecting=False):
        """Show Connect as the host-session toggle.

        While the CONNECT handshake is unanswered the action cancels it, so the
        user is not held by the handshake deadline. Bluetooth peer connection
        has its own adjacent connect/disconnect toggle.
        """
        state = "connecting" if connecting else ("connected" if connected else "disconnected")
        if state == self._connection_state:
            return
        self._connection_state = state
        label, glyph = self.CONNECTION_STATES[state]
        action = self.toolbar_actions["Connect"]
        action.setIcon(icons.icon(glyph))
        action.setText(label)
        action.setToolTip(label)
        action.setStatusTip(label)
        self.buttons["Connect"].setToolTip(label)

    def set_peer_connection_state(self, connected):
        """Use one peer-link action for both connect and disconnect."""
        label = "Disconnect peer" if connected else "Connect peer"
        glyph = "disconnect" if connected else "link-connect"
        action = self.toolbar_actions["Connect peer"]
        action.setIcon(icons.icon(glyph))
        action.setText(label)
        action.setToolTip(label)
        action.setStatusTip(label)
        self.buttons["Connect peer"].setToolTip(label)
