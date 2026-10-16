"""visualize.py -- floor-plan overlay for an output JSON (slide-8 format).

Shows: room zones coloured by hub, doors / open passages, hub and node ids, the visiting
order on every leg, the closed return leg (dashed), and violations in red.

    draw(data, room_shapes, "out.png", doors=..., report=..., title=..., banner=...)

data         output JSON dict (panel_routing.output.to_json)
room_shapes  {"R01": [(x, y), ...], ...}  room outlines in metres
doors        [((x0, y0), (x1, y1)), ...]   door / open-passage gaps, drawn as thick ticks
report       result of panel_routing.validator.validate (optional)
banner       text shown in a warning box; pass one whenever the data is not official
"""
import math
import re

COLORS = ["#1f77b4", "#2ca02c", "#9467bd", "#17becf", "#7f7f7f"]
RED = "#d62728"


def _along(poly, frac):
    """Point and unit direction at a fraction of the way along a polyline."""
    lens = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
    total = sum(lens)
    if total == 0:
        return tuple(poly[0]), (1.0, 0.0)
    target, acc = frac * total, 0.0
    for i, L in enumerate(lens):
        if L > 0 and acc + L >= target:
            t = (target - acc) / L
            a, b = poly[i], poly[i + 1]
            return ((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])),
                    ((b[0] - a[0]) / L, (b[1] - a[1]) / L))
        acc += L
    return tuple(poly[-1]), (1.0, 0.0)


def draw(data, room_shapes, path, doors=(), report=None, title="", banner=None,
         room_labels=None, show=False):
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Polygon as MplPolygon

    hubs = data["hubs"]
    violations = (report or {}).get("violations", [])
    bad_hubs = {v["hub"] for v in violations if v.get("hub")}
    room_hub = {r: k for k, h in enumerate(hubs) for r in h["assigned_rooms"]}

    fig, ax = plt.subplots(figsize=(12, 8.5))
    xs = [p[0] for ring in room_shapes.values() for p in ring]
    ys = [p[1] for ring in room_shapes.values() for p in ring]

    # ---- rooms, coloured by hub zone ----------------------------------------------------
    for name, ring in room_shapes.items():
        k = room_hub.get(name)
        color = COLORS[k % len(COLORS)] if k is not None else "#bbbbbb"
        ax.add_patch(MplPolygon(ring, closed=True, facecolor=color, alpha=0.16,
                                edgecolor="#333333", lw=1.8, zorder=1))
        label = (room_labels or {}).get(name, name)
        ax.text(min(p[0] for p in ring) + 0.2, max(p[1] for p in ring) - 0.2, label,
                fontsize=8, color="#444444", ha="left", va="top", zorder=2)

    # ---- doors / open passages ----------------------------------------------------------
    for a, b in doors:
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#222222", lw=9, solid_capstyle="butt", zorder=3)
        ax.plot([a[0], b[0]], [a[1], b[1]], color="#ffe08a", lw=6, solid_capstyle="butt", zorder=3)

    # ---- rings: legs, arrows, visiting order, closed return leg -------------------------
    node_xy = {}
    for k, h in enumerate(hubs):
        color = COLORS[k % len(COLORS)]
        segs = h["route_segments"]
        for seg in segs:
            node_xy[seg["to"]] = tuple(seg["polyline"][-1])
        for j, seg in enumerate(segs):
            poly = seg["polyline"]
            px = [p[0] for p in poly]
            py = [p[1] for p in poly]
            if h["hub_id"] in bad_hubs:                       # red halo under an offending ring
                ax.plot(px, py, color=RED, lw=7, alpha=0.35, zorder=3.5, solid_joinstyle="round")
            last = j == len(segs) - 1
            ax.plot(px, py, color=color, lw=2.4, ls="--" if last else "-", zorder=4,
                    solid_joinstyle="round")
            (ax_, ay_), (dx, dy) = _along(poly, 0.62)
            ax.annotate("", xy=(ax_ + 0.18 * dx, ay_ + 0.18 * dy), xytext=(ax_ - 0.18 * dx, ay_ - 0.18 * dy),
                        arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8, shrinkA=0, shrinkB=0), zorder=5)
            (lx, ly), _ = _along(poly, 0.34)
            ax.text(lx, ly, f"{j + 1} return" if last else str(j + 1), fontsize=8, ha="center",
                    va="center", zorder=7, bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=color, lw=1.2))

    # ---- hubs and nodes -----------------------------------------------------------------
    for k, h in enumerate(hubs):
        color = COLORS[k % len(COLORS)]
        hx, hy = h["location"]["x"], h["location"]["y"]
        ax.scatter([hx], [hy], marker="s", s=190, color=color, edgecolor="black", lw=1.4, zorder=8)
        ax.text(hx + 0.3, hy + 0.3, h["hub_id"], fontsize=10, weight="bold", zorder=9,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=color, lw=1.2))
        for n in h["assigned_nodes"]:
            if n in node_xy:
                x, y = node_xy[n]
                ax.scatter([x], [y], marker="o", s=100, facecolor="white", edgecolor=color, lw=2.4, zorder=8)
                ax.text(x + 0.28, y - 0.45, n, fontsize=9, zorder=9, color="#111111")

    # ---- violations ---------------------------------------------------------------------
    for v in violations:
        m = re.search(r"\(\s*(-?[\d.]+),\s*(-?[\d.]+)\)", v["message"]) if v["rule"] == "free_space" else None
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            ax.scatter([x], [y], marker="X", s=320, color=RED, edgecolor="white", lw=1.2, zorder=10)
            ax.text(x + 0.35, y + 0.35, "cable outside free space", color=RED, fontsize=9,
                    weight="bold", zorder=10, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=RED))

    # ---- frame, title, status, banner, legend -------------------------------------------
    ax.set_xlim(min(xs) - 0.6, max(xs) + 0.6)
    ax.set_ylim(min(ys) - 0.6, max(ys) + 0.6)
    ax.set_aspect("equal")
    ax.grid(alpha=0.15)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    metrics = (report or {}).get("metrics")
    line = ""
    if metrics:
        line = (f"\nH={len(hubs)}   L={metrics['L']:.1f} m   X={metrics['X']}   "
                f"O={metrics['O']:.1f} m   B={metrics['B']}   J={metrics['J']:.1f}")
    ax.set_title(title + line, fontsize=11, loc="left")
    if report is not None:
        ok = report["valid"]
        fig.text(0.985, 0.915, "VALID: all checks passed" if ok else f"INVALID: {len(violations)} violation(s)",
                 ha="right", va="top", fontsize=11, weight="bold", color="#1a7f37" if ok else RED)
    if banner:
        fig.text(0.5, 0.985, banner, ha="center", va="top", fontsize=11, weight="bold", color="#b00020",
                 bbox=dict(boxstyle="round,pad=0.4", fc="#fff3cd", ec="#b00020"))
        ax.text(0.5, 0.5, "SYNTHETIC", transform=ax.transAxes, fontsize=90, color="black", alpha=0.045,
                ha="center", va="center", rotation=25, zorder=0)

    handles = [Line2D([0], [0], marker="s", color=COLORS[k % len(COLORS)], lw=2.4, markersize=9,
                      markeredgecolor="black",
                      label=f"{h['hub_id']}: {', '.join(h['assigned_rooms'])}  ({h['ring_length_m']:.1f} m)")
               for k, h in enumerate(hubs)]
    handles += [Line2D([0], [0], color="#555555", lw=2.4, label="cable leg (number = visiting order)"),
                Line2D([0], [0], color="#555555", lw=2.4, ls="--", label="closed return leg to the hub"),
                Line2D([0], [0], marker="o", color="w", markerfacecolor="white", markeredgecolor="#555555",
                       markeredgewidth=2, markersize=9, label="node (fixed)"),
                Line2D([0], [0], color="#ffe08a", lw=6, label="door / open passage")]
    if violations:
        handles.append(Line2D([0], [0], color=RED, lw=6, alpha=0.5, label="ring with a violation"))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8, frameon=True)

    bottom = 0.07
    if violations:
        lines = [f"[{v['rule']}] {v.get('hub') or ''}: {v['message']}"[:130] for v in violations[:6]]
        if len(violations) > 6:
            lines.append(f"... and {len(violations) - 6} more")
        fig.text(0.01, 0.01, "\n".join(lines), ha="left", va="bottom", fontsize=7.5, color=RED, family="monospace")
        bottom = 0.06 + 0.022 * len(lines)
    fig.subplots_adjust(left=0.06, right=0.76, top=0.87, bottom=bottom)
    fig.savefig(path, dpi=150)
    if show:
        plt.show()
    plt.close(fig)
    return path
