"""Generate the timing figures for the deck.

images/mode-N-timing.svg: CS step segments from the planner's own model
(ble_channel_sounding_planner.model.step_segments) with its default scenario, drawn to scale
in the style of the planner's "Individual step" view, so the slides match what the app shows.
The one exception is the antenna configuration: ACI 6 (1:4, four antenna paths) instead of the
default single path, so the tone modes show one tone slot per path, as on the antenna slide.

images/acl-interval-layout.svg: one 72-channel procedure and its RAS transfer at three ACL
intervals, drawn to scale from the host application's planner (ble_channel_sounding.planner.model:
build_schedule and its RAS transfer model), with the step timings our nRF54 pair selected.

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

from ble_channel_sounding.planner import model as host_model  # noqa: E402
from ble_channel_sounding_planner.model import ANTENNA_PATHS, Scenario, step_segments  # noqa: E402
# The planner's colours (ScenarioWindow.draw_step), lightened for the deck's
# dark background.
COLORS = {0: "#c5a3f2", 1: "#78cbd8", 2: "#65e4d0", 3: "#ffb17a"}
GAP_COLOR = "#6f9199"
EXTENSION_COLOR = "#d9bd86"
BACKGROUND = "#09242b"
TEXT, MUTED, GRID = "#f5f5ed", "#afc8cb", "#24454d"
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
                out.append(label_svg(p.label, x + w / 2, y + BLOCK_H / 2 + size / 3, size, BACKGROUND, "bold"))
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
    aci = s.procedure.tone_antenna_config_selection
    paths = ANTENNA_PATHS[aci]
    interlude = f"T_IP1 = {c.t_ip1_time_us} µs" if mode in (0, 1) else \
        f"T_IP2 = {c.t_ip2_time_us} µs, T_SW = {s.t_sw_us} µs, T_PM = {c.t_pm_time_us} µs; " \
        f"{paths} antenna path{'s' if paths > 1 else ''} (ACI {aci})"
    note = f"Mode {mode} step: {total} µs, drawn to scale. Planner defaults: {phy} CS_SYNC, {interlude}."
    height = AXIS_Y + 122
    out.append(f'<text x="{LEFT}" y="{height - 8}" font-size="15" fill="{MUTED}">{escape(note)}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" font-family="{FONT}">\n'
            f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>\n' + "\n".join(out) + "\n</svg>\n")


ACL_COLOR, RAS_COLOR = "#86b8dc", "#ffb17a"  # planner ACL blocks; the deck's Peripheral colour
NEXT_OPACITY = 0.45

# The step timings our nRF54 pair selected in configuration complete (implementation_plan.md
# §8.5, 2026-09-19): T_IP1 30, T_IP2 20, T_FCS 60 µs, and the firmware's T_PM 10 µs.
LAB_TIMINGS = dict(t_ip1_time_us=30, t_ip2_time_us=20, t_fcs_time_us=60, t_pm_time_us=10)


def interval_scenario(interval, subevent_len, procedure_interval=100):
    """72 channels once, mode 2, two mode-0 steps, CS_SYNC LE 1M, one antenna path, ATT MTU 498.

    One subevent per CS event and one CS event per ACL interval. The 1 ms CS offset is the
    lead a CS event needs on this controller (Offset_Min 500 µs and the SDC's set-up); the
    subevent length leaves that lead free, as host_model.validate() requires.
    """
    s = host_model.Scenario()
    return replace(
        s,
        connection=replace(s.connection, interval_min=interval, interval_max=interval, interval=interval, mtu=498),
        configuration=replace(s.configuration, mode=2, mode_0_steps=2, cs_sync_phy=1, **LAB_TIMINGS),
        procedure=replace(s.procedure, subevent_len=subevent_len, subevents_per_event=1, subevent_interval=0,
                          event_interval=1, procedure_interval=procedure_interval, max_procedure_len=0xFFFF),
        event_offset_us=1000)


def interval_layout(interval, subevent_len):
    """Schedule one procedure and its RAS transfer; the next procedure starts after both."""
    schedule = host_model.build_schedule(interval_scenario(interval, subevent_len))
    assert not schedule.errors, schedule.errors
    s = interval_scenario(interval, subevent_len)
    period = s.connection.interval_us
    end = s.event_offset_us + schedule.duration
    ras_first = -(-end // period)  # first ACL anchor after the last CS event
    procedure_interval = ras_first + schedule.ras.events
    s = interval_scenario(interval, subevent_len, procedure_interval)
    schedule = host_model.build_schedule(s)
    assert not schedule.errors, schedule.errors
    return s, schedule, ras_first


def interval_figure(rows):
    width, left, right, total = 1200, 170, 40, 64000
    scale = (width - left - right) / total
    ms = lambda us: f"{us / 1000:g}"  # noqa: E731

    def x(us):
        return left + min(us, total) * scale

    row_h, top = 112, 16
    axis_y = top + len(rows) * row_h + 4
    out = []
    for r, (interval, subevent_len) in enumerate(rows):
        s, schedule, ras_first = interval_layout(interval, subevent_len)
        period, p = s.connection.interval_us, s.procedure
        y = top + r * row_h
        acl_y, cs_y, cs_h = y + 6, y + 30, 32
        out.append(f'<text x="{left - 16}" y="{y + 36}" text-anchor="end" font-size="26" font-weight="bold" '
                   f'fill="{TEXT}">{ms(period)} ms</text>')
        out.append(f'<text x="{left - 16}" y="{y + 60}" text-anchor="end" font-size="16" fill="{MUTED}">'
                   f'ACL interval</text>')
        ras_anchors = range(ras_first, ras_first + schedule.ras.events)
        for k in range(total // period + 1):
            anchor = k * period
            out.append(f'<line x1="{x(anchor):.1f}" y1="{acl_y - 4}" x2="{x(anchor):.1f}" y2="{cs_y + cs_h + 4}" '
                       f'stroke="{GRID}" stroke-width="2"/>')
            if k in ras_anchors:
                span = schedule.ras.spans[k - ras_first]
                out.append(f'<rect x="{x(anchor):.1f}" y="{acl_y}" width="{x(anchor + span) - x(anchor):.1f}" '
                           f'height="18" fill="{RAS_COLOR}"/>')
            else:
                out.append(f'<rect x="{x(anchor):.1f}" y="{acl_y}" width="{x(anchor + 400) - x(anchor):.1f}" '
                           f'height="18" fill="{ACL_COLOR}"/>')
        spacing = p.procedure_interval * period
        for start, opacity in ((0, 1), (spacing, NEXT_OPACITY)):
            for se in schedule.subevents:
                for step in se.steps:
                    begin = start + s.event_offset_us + step.start
                    if begin >= total:
                        continue
                    out.append(f'<rect x="{x(begin):.1f}" y="{cs_y}" width="{x(begin + step.duration) - x(begin):.2f}" '
                               f'height="{cs_h}" fill="{COLORS[step.mode]}" opacity="{opacity}"/>')
        a, b, by = s.event_offset_us, s.event_offset_us + spacing, cs_y + cs_h + 22
        rate = 1e6 / spacing
        label = (f"procedure interval {p.procedure_interval} × {ms(period)} ms = {ms(spacing)} ms · "
                 f"{rate:.0f} procedures/s · {schedule.event_count} CS event{'s' if schedule.event_count > 1 else ''}, "
                 f"{schedule.ras.events} RAS event{'s' if schedule.ras.events > 1 else ''}")
        out.append(f'<line x1="{x(a):.1f}" y1="{by}" x2="{x(b):.1f}" y2="{by}" stroke="{TEXT}" stroke-width="1.5"/>')
        for edge in (a, b):
            if edge <= total:
                out.append(f'<line x1="{x(edge):.1f}" y1="{by - 6}" x2="{x(edge):.1f}" y2="{by + 6}" '
                           f'stroke="{TEXT}" stroke-width="1.5"/>')
        out.append(f'<text x="{x(a) + 4:.1f}" y="{by + 24}" font-size="17" fill="{TEXT}">{escape(label)}</text>')

    out.append(f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" stroke="{MUTED}"/>')
    for t in range(0, total + 1, 10000):
        out.append(f'<line x1="{x(t):.1f}" y1="{axis_y}" x2="{x(t):.1f}" y2="{axis_y + 6}" stroke="{MUTED}"/>')
        out.append(label_svg(ms(t), x(t), axis_y + 26, 18, MUTED))
    out.append(f'<text x="{left - 16}" y="{axis_y + 26}" text-anchor="end" font-size="18" fill="{MUTED}">ms</text>')

    legend = [(COLORS[0], "Mode 0"), (COLORS[2], "Mode 2 (PBR)"), (ACL_COLOR, "ACL event"),
              (RAS_COLOR, "ACL event carrying RAS data")]
    lx, ly = left, axis_y + 52
    for color, name in legend:
        out.append(f'<rect x="{lx}" y="{ly}" width="20" height="20" fill="{color}"/>')
        out.append(f'<text x="{lx + 28}" y="{ly + 17}" font-size="18" fill="{TEXT}">{escape(name)}</text>')
        lx += 28 + text_width(name, 18) * 0.85 + 30
    out.append(f'<rect x="{lx}" y="{ly}" width="20" height="20" fill="{COLORS[2]}" opacity="{NEXT_OPACITY}"/>')
    out.append(f'<text x="{lx + 28}" y="{ly + 17}" font-size="18" fill="{TEXT}">next procedure</text>')

    note = ("To scale (planner): 72 channels, mode 2, our nRF54 step timings, RAS at MTU 498 on LE 1M; "
            "offset and ACL events illustrative.")
    height = ly + 52
    out.append(f'<text x="{left}" y="{height - 8}" font-size="16" fill="{MUTED}">{escape(note)}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{FONT}">\n'
            f'<rect width="100%" height="100%" fill="{BACKGROUND}"/>\n' + "\n".join(out) + "\n</svg>\n")


def main():
    s = Scenario()
    s = replace(s, procedure=replace(s.procedure, tone_antenna_config_selection=6))
    images = Path(__file__).resolve().parent / "images"
    for mode in range(4):
        path = images / f"mode-{mode}-timing.svg"
        path.write_text(figure(s, mode), encoding="utf-8")
        print(path.relative_to(ROOT))
    path = images / "acl-interval-layout.svg"
    path.write_text(interval_figure(((6, 6000), (12, 12000), (24, 12000))), encoding="utf-8")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
