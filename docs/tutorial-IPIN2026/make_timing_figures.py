"""Generate the timing figures for the deck.

images/mode-N-timing.svg: CS step segments from the planner's own model
(ble_channel_sounding_planner.model.step_segments) with its default scenario, drawn to scale
in the style of the planner's "Individual step" view, so the slides match what the app shows.

images/acl-cs-timing.svg: CS procedures placed on the ACL connection timeline, with
the firmware's default connection and procedure parameters and the steps from the
planner's build_schedule, drawn to scale.

Run from the repository root:

    .venv/bin/python docs/tutorial-IPIN2026/make_timing_figures.py
"""

from dataclasses import replace
from html import escape
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from ble_channel_sounding_planner.model import ANTENNA_PATHS, Scenario, build_schedule, step_segments  # noqa: E402
from ble_channel_sounding_planner.view import COLORS  # noqa: E402

GAP_COLOR = "#a6b6ca"  # same colours as ScenarioWindow.draw_step
EXTENSION_COLOR = "#c4a269"
TEXT, MUTED, GRID = "#21334b", "#536981", "#e3e9f0"
FONT = "Arial, Helvetica, sans-serif"

WIDTH, LEFT, RIGHT = 1200, 130, 30
LANES = (("Initiator", "Initiator TX", 30), ("Reflector", "Reflector TX", 135), ("Timing", "Timing", 240))
BLOCK_H, AXIS_Y = 50, 320
TICK_US = 50
# Narrow segments are labelled under their lane, most important first, on up to two rows.
BELOW_PRIORITY = ("CS_SYNC", "T_GD", "T_RD", "T_FM")


def text_width(label, size):
    return len(label) * size * 0.6


def label_svg(label, x, y, size, color, weight="normal"):
    """Centered label; T_XX is drawn as T with a subscript."""
    m = re.fullmatch(r"T_(\w+)", label)
    body = (f'T<tspan dy="{size * 0.3:.1f}" font-size="{size * 0.72:.1f}">{escape(m.group(1))}</tspan>'
            if m else escape(label))
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}">{body}</text>')


def figure(s, mode):
    parts = step_segments(s, mode)
    total = sum(p.duration for p in parts)
    scale = (WIDTH - LEFT - RIGHT) / total
    out = []

    ticks = list(range(0, total, TICK_US))
    if total - ticks[-1] < TICK_US * 0.4:
        ticks.pop()
    for t in ticks + [total]:
        x = LEFT + t * scale
        out.append(f'<line x1="{x:.1f}" y1="15" x2="{x:.1f}" y2="{AXIS_Y}" stroke="{GRID}"/>')
        out.append(f'<line x1="{x:.1f}" y1="{AXIS_Y}" x2="{x:.1f}" y2="{AXIS_Y + 6}" stroke="{MUTED}"/>')
        out.append(label_svg(str(t), x, AXIS_Y + 24, 16, MUTED))
    out.append(f'<line x1="{LEFT}" y1="{AXIS_Y}" x2="{WIDTH - RIGHT}" y2="{AXIS_Y}" stroke="{MUTED}"/>')
    out.append(label_svg("Time since step start (µs)", LEFT + (WIDTH - LEFT - RIGHT) / 2, AXIS_Y + 50, 16, MUTED))

    for lane, title, y in LANES:
        out.append(f'<text x="{LEFT - 14}" y="{y + BLOCK_H / 2 + 6}" text-anchor="end" font-size="18" '
                   f'fill="{MUTED}">{title}</text>')
        below = []
        for p in (p for p in parts if p.lane == lane):
            x, w = LEFT + p.start * scale, p.duration * scale
            gap = p.label.startswith("T_") and p.label != "T_FM"
            color = EXTENSION_COLOR if p.label == "Extension" else GAP_COLOR if gap else COLORS[mode]
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{BLOCK_H}" fill="{color}"/>')
            size = next((z for z in (17, 14) if w > text_width(p.label, z) + 6), None)
            if size:
                out.append(label_svg(p.label, x + w / 2, y + BLOCK_H / 2 + size / 3, size, "#ffffff", "bold"))
            else:
                below.append(p)
        rows = ([], [])  # occupied (left, right) spans per row
        rank = {name: i for i, name in enumerate(BELOW_PRIORITY)}
        for p in sorted(below, key=lambda p: rank.get(p.label, len(rank))):
            cx = LEFT + (p.start + p.duration / 2) * scale
            half = text_width(p.label, 15) / 2 + 3
            row = next((i for i, spans in enumerate(rows)
                        if all(cx + half < a or cx - half > b for a, b in spans)), None)
            if row is not None:
                rows[row].append((cx - half, cx + half))
                out.append(label_svg(p.label, cx, y + BLOCK_H + 18 + row * 18, 15, TEXT))

    legend = [(COLORS[mode], "Transmission"), (GAP_COLOR, "Guard, ramp-down, switch or interlude")]
    if mode in (2, 3):
        legend.append((EXTENSION_COLOR, "Tone extension slot"))
    x = LEFT
    for color, name in legend:
        out.append(f'<rect x="{x}" y="{AXIS_Y + 72}" width="18" height="18" fill="{color}"/>')
        out.append(f'<text x="{x + 26}" y="{AXIS_Y + 87}" font-size="16" fill="{TEXT}">{escape(name)}</text>')
        x += 26 + text_width(name, 16) * 0.9 + 40

    c = s.configuration
    phy = "LE 1M" if c.cs_sync_phy == 1 else "LE 2M"
    interlude = f"T_IP1 = {c.t_ip1_time_us} µs" if mode in (0, 1) else \
        f"T_IP2 = {c.t_ip2_time_us} µs, T_SW = {s.t_sw_us} µs, T_PM = {c.t_pm_time_us} µs, " \
        f"{ANTENNA_PATHS[s.procedure.tone_antenna_config_selection]} antenna path"
    note = f"Mode {mode} step: {total} µs, drawn to scale. Planner defaults: {phy} CS_SYNC, {interlude}."
    height = AXIS_Y + 122
    out.append(f'<text x="{LEFT}" y="{height - 8}" font-size="15" fill="{MUTED}">{escape(note)}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" font-family="{FONT}">\n'
            f'<rect width="100%" height="100%" fill="#ffffff"/>\n' + "\n".join(out) + "\n</svg>\n")


ACL_COLOR, RAS_COLOR = "#527ba8", "#c8641e"  # planner ACL blocks; the deck's Peripheral colour


def acl_scenario():
    """Firmware defaults (common/libs/cs_utils/cs_config.c) on the planner scenario.

    Connection interval 6 x 1.25 ms and a 6 ms subevent budget with mode 2 and a mode-1
    sub-mode. The controller picks the procedure interval from 1-4; 2 is drawn. One
    subevent per event and the planner's 1.5 ms CS offset and 1 ms ACL activity are
    assumptions for the illustration.
    """
    s = Scenario()
    return replace(
        s,
        connection=replace(s.connection, interval_min=6, interval_max=6, interval=6),
        configuration=replace(s.configuration, mode=0x12),
        procedure=replace(s.procedure, subevent_len=6000, subevents_per_event=1, subevent_interval=0,
                          event_interval=1, procedure_interval=2, max_procedure_len=10))


def acl_figure(s):
    schedule = build_schedule(s)
    assert not schedule.errors, schedule.errors
    interval, p = s.connection.interval_us, s.procedure
    spacing = p.procedure_interval * interval
    anchors = 4
    total = anchors * interval + s.connection.activity_us
    width, left, right = 1200, 180, 30
    scale = (width - left - right) / total
    ms = lambda us: f"{us / 1000:g}"  # noqa: E731

    def x(us):
        return left + us * scale

    def bracket(a, b, y, label, color=MUTED, size=19):
        return (f'<line x1="{x(a):.1f}" y1="{y}" x2="{x(b):.1f}" y2="{y}" stroke="{color}" stroke-width="1.5"/>'
                f'<line x1="{x(a):.1f}" y1="{y - 6}" x2="{x(a):.1f}" y2="{y + 6}" stroke="{color}" stroke-width="1.5"/>'
                f'<line x1="{x(b):.1f}" y1="{y - 6}" x2="{x(b):.1f}" y2="{y + 6}" stroke="{color}" stroke-width="1.5"/>'
                f'<text x="{(x(a) + x(b)) / 2:.1f}" y="{y - 10}" text-anchor="middle" font-size="{size}" '
                f'fill="{color}">{escape(label)}</text>')

    acl_y, cs_y, lane_h, axis_y = 80, 190, 44, 330
    out = []
    for i in range(anchors + 1):
        ax = x(i * interval)
        out.append(f'<line x1="{ax:.1f}" y1="{acl_y - 12}" x2="{ax:.1f}" y2="{axis_y}" stroke="{GRID}" stroke-width="2"/>')
        out.append(f'<line x1="{ax:.1f}" y1="{axis_y}" x2="{ax:.1f}" y2="{axis_y + 6}" stroke="{MUTED}"/>')
        out.append(label_svg(ms(i * interval), ax, axis_y + 26, 19, MUTED))
    out.append(f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" stroke="{MUTED}"/>')
    out.append(label_svg("Time since ACL anchor (ms)", left + (width - left - right) / 2, axis_y + 54, 19, MUTED))

    for title, y in (("ACL events", acl_y), ("CS procedure", cs_y)):
        out.append(f'<text x="{left - 14}" y="{y + lane_h / 2 + 7}" text-anchor="end" font-size="22" '
                   f'fill="{MUTED}">{title}</text>')

    out.append(bracket(0, interval, 40, f"connection interval {ms(interval)} ms"))
    procedures = range(0, anchors * interval, spacing)
    for i in range(anchors):
        anchor = i * interval
        carries_cs = anchor in procedures
        color = ACL_COLOR if carries_cs else RAS_COLOR
        out.append(f'<rect x="{x(anchor):.1f}" y="{acl_y}" width="{s.connection.activity_us * scale:.1f}" '
                   f'height="{lane_h}" fill="{color}"/>')
        if not carries_cs:
            out.append(f'<text x="{x(anchor) + 6:.1f}" y="{acl_y + lane_h + 22}" font-size="19" '
                       f'fill="{RAS_COLOR}">RAS results</text>')
    out.append(f'<rect x="{x(anchors * interval):.1f}" y="{acl_y}" width="{s.connection.activity_us * scale:.1f}" '
               f'height="{lane_h}" fill="{ACL_COLOR}"/>')

    steps = [step for se in schedule.subevents for step in se.steps]
    for start in procedures:
        origin = start + s.event_offset_us
        for step in steps:
            out.append(f'<rect x="{x(origin + step.start):.1f}" y="{cs_y}" '
                       f'width="{step.duration * scale:.1f}" height="{lane_h}" fill="{COLORS[step.mode]}"/>')
        out.append(f'<text x="{x(origin + schedule.duration / 2):.1f}" y="{cs_y - 10}" text-anchor="middle" '
                   f'font-size="19" fill="{TEXT}">{len(steps)} steps, {schedule.duration / 1000:.2f} ms</text>')
    out.append(bracket(0, s.event_offset_us, cs_y + lane_h + 24, "offset"))
    out.append(bracket(s.event_offset_us, s.event_offset_us + spacing, cs_y + lane_h + 66,
                       f"procedure interval {p.procedure_interval} × {ms(interval)} ms = {ms(spacing)} ms", TEXT))

    legend = [(COLORS[0], "Mode 0"), (COLORS[2], "Mode 2 (PBR)"), (COLORS[1], "Mode 1 (RTT)"),
              (ACL_COLOR, "ACL event"), (RAS_COLOR, "ACL event with RAS data")]
    lx = left
    for color, name in legend:
        out.append(f'<rect x="{lx}" y="{axis_y + 76}" width="20" height="20" fill="{color}"/>')
        out.append(f'<text x="{lx + 28}" y="{axis_y + 93}" font-size="19" fill="{TEXT}">{escape(name)}</text>')
        lx += 28 + text_width(name, 19) * 0.85 + 30

    note = (f"CS steps to scale (planner, firmware defaults); "
            f"ACL airtime and the {ms(s.event_offset_us)} ms offset are illustrative.")
    height = axis_y + 134
    out.append(f'<text x="{left}" y="{height - 8}" font-size="18" fill="{MUTED}">{escape(note)}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{FONT}">\n'
            f'<rect width="100%" height="100%" fill="#ffffff"/>\n' + "\n".join(out) + "\n</svg>\n")


def main():
    s = Scenario()
    images = Path(__file__).resolve().parent / "images"
    for mode in range(4):
        path = images / f"mode-{mode}-timing.svg"
        path.write_text(figure(s, mode), encoding="utf-8")
        print(path.relative_to(ROOT))
    path = images / "acl-cs-timing.svg"
    path.write_text(acl_figure(acl_scenario()), encoding="utf-8")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
