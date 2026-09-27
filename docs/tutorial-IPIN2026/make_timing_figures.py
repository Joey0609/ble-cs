"""Generate the CS step timing figures (images/mode-N-timing.svg) for the deck.

The segments come from the planner's own model (cs_planner.model.step_segments)
with its default scenario, and are drawn to scale in the style of the planner's
"Individual step" view, so the slides match what the app shows.

Run from the repository root:

    .venv/bin/python docs/tutorial-IPIN2026/make_timing_figures.py
"""

from html import escape
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cs_planner.model import ANTENNA_PATHS, Scenario, step_segments  # noqa: E402
from cs_planner.view import COLORS  # noqa: E402

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


def main():
    s = Scenario()
    images = Path(__file__).resolve().parent / "images"
    for mode in range(4):
        path = images / f"mode-{mode}-timing.svg"
        path.write_text(figure(s, mode), encoding="utf-8")
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
