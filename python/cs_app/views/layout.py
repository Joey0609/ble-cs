"""Shared layout helpers for the top panel groups."""
from PyQt6 import QtCore, QtWidgets as W


def compact_form(parent):
    """A tight, left-aligned form (the macOS style otherwise centres rows and adds generous spacing)."""
    form = W.QFormLayout(parent)
    left = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
    form.setLabelAlignment(left)
    form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
    form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setContentsMargins(8, 4, 8, 6)
    form.setVerticalSpacing(4)
    return form
