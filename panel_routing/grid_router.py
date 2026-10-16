"""Axis-aligned (horizontal / vertical) cable routing on a grid.

The grid has uniform lines every `step` metres PLUS a line through every terminal,
so hubs and nodes sit exactly on grid points and legs start / end exactly on them.
A grid edge exists only if it lies fully inside the free space (rooms + doors /
openings, minus walls and windows), so a path can never cross a wall, window or the
exterior, and passes between rooms only through door gaps.

Search is Dijkstra over (node, direction) states. Cost per leg, in the checker's units:
    length (1/m) + 0.5 per bend
    + overlap_cost * length for each earlier leg already on the same edge
    + cross_cost for meeting earlier cable at a grid node (terminals excepted)
so routing legs one after another (route_ring) naturally prefers parallel lanes over
retraces and avoids crossing other cable.
"""
import heapq
import math

import numpy as np

E, N, W, S = 0, 1, 2, 3
_DX = (1, 0, -1, 0)
_DY = (0, 1, 0, -1)


class Usage:
    """Cable already laid; shared across rings so later rings see earlier ones."""

    def __init__(self):
        self.edge = {}       # (lower node index, axis) -> number of legs on that edge
        self.node_axes = {}  # node index -> bitmask, 1 = horizontal cable, 2 = vertical cable


class GridRouter:
    def __init__(self, inside, bbox, terminals, step=0.1,
                 bend_cost=0.5, overlap_cost=1.0, cross_cost=5.0):
        """inside(xs, ys) -> bool array, vectorised: True where a cable may run."""
        self.step = step
        self.bend, self.overlap, self.cross = bend_cost, overlap_cost, cross_cost
        x0, y0, x1, y1 = bbox
        tx = [float(t[0]) for t in terminals]
        ty = [float(t[1]) for t in terminals]
        self.xs = self._lines(x0, x1, tx)
        self.ys = self._lines(y0, y1, ty)
        nx, ny = len(self.xs), len(self.ys)
        self.nx, self.ny = nx, ny
        X, Y = np.meshgrid(self.xs, self.ys)
        ok = np.asarray(inside(X.ravel(), Y.ravel()), dtype=bool).reshape(ny, nx)
        self.ok = ok

        hvalid = ok[:, :-1] & ok[:, 1:]
        vvalid = ok[:-1, :] & ok[1:, :]
        for f in (0.25, 0.5, 0.75):               # sample inside each edge: catches thin walls
            xm = self.xs[:-1] + f * np.diff(self.xs)
            XM, YM = np.meshgrid(xm, self.ys)
            hvalid &= np.asarray(inside(XM.ravel(), YM.ravel()), dtype=bool).reshape(ny, nx - 1)
            ym = self.ys[:-1] + f * np.diff(self.ys)
            XM, YM = np.meshgrid(self.xs, ym)
            vvalid &= np.asarray(inside(XM.ravel(), YM.ravel()), dtype=bool).reshape(ny - 1, nx)

        total = nx * ny
        self.nbr = [[-1] * total for _ in range(4)]
        self.elen = [[0.0] * total for _ in range(4)]
        dxs, dys = np.diff(self.xs), np.diff(self.ys)
        for j in range(ny):
            for i in range(nx):
                n = j * nx + i
                if i < nx - 1 and hvalid[j, i]:
                    self.nbr[E][n], self.elen[E][n] = n + 1, float(dxs[i])
                if i > 0 and hvalid[j, i - 1]:
                    self.nbr[W][n], self.elen[W][n] = n - 1, float(dxs[i - 1])
                if j < ny - 1 and vvalid[j, i]:
                    self.nbr[N][n], self.elen[N][n] = n + nx, float(dys[j])
                if j > 0 and vvalid[j - 1, i]:
                    self.nbr[S][n], self.elen[S][n] = n - nx, float(dys[j - 1])

        self.term_nodes = set()
        for p in terminals:
            try:
                self.term_nodes.add(self.node_of(p))
            except ValueError:
                pass

    # ------------------------------------------------------------------ grid helpers
    def _lines(self, lo, hi, extra):
        uniform = np.arange(lo, hi + self.step * 0.5, self.step)
        keep = [u for u in uniform if all(abs(u - e) > 0.3 * self.step for e in extra)]
        return np.unique(np.round(np.array(keep + list(extra)), 6))

    def node_of(self, p):
        i = int(np.argmin(np.abs(self.xs - p[0])))
        j = int(np.argmin(np.abs(self.ys - p[1])))
        if abs(self.xs[i] - p[0]) > 1e-5 or abs(self.ys[j] - p[1]) > 1e-5:
            raise ValueError(f"point {p} is not a registered terminal of this router")
        return j * self.nx + i

    def xy(self, n):
        return (float(self.xs[n % self.nx]), float(self.ys[n // self.nx]))

    def is_free(self, p):
        try:
            n = self.node_of(p)
        except ValueError:
            return False
        return bool(self.ok[n // self.nx, n % self.nx])

    def new_usage(self):
        return Usage()

    # ------------------------------------------------------------------ search
    def _search(self, src, targets, prev_dir=None, usage=None):
        INF = math.inf
        dist, pred, heap = {}, {}, []
        for d in range(4):
            c = 0.0 if prev_dir is None or d == prev_dir else self.bend
            dist[src * 4 + d] = c
            heapq.heappush(heap, (c, src * 4 + d))
        remaining, found = set(targets), {}
        while heap and remaining:
            c, s = heapq.heappop(heap)
            if c > dist.get(s, INF):
                continue
            n, d = divmod(s, 4)
            if n in remaining:
                found[n] = (c, s)
                remaining.discard(n)
                if not remaining:
                    break
            m = self.nbr[d][n]
            if m >= 0:
                w = self.elen[d][n]
                if usage is not None:
                    axis = d % 2
                    w += self.overlap * w * usage.edge.get((min(n, m), axis), 0)
                    other = 2 if axis == 0 else 1
                    if usage.node_axes.get(m, 0) & other and m not in self.term_nodes:
                        w += self.cross
                t = m * 4 + d
                if c + w < dist.get(t, INF):
                    dist[t] = c + w
                    pred[t] = s
                    heapq.heappush(heap, (c + w, t))
            for d2 in range(4):
                if d2 != d:
                    t = n * 4 + d2
                    if c + self.bend < dist.get(t, INF):
                        dist[t] = c + self.bend
                        pred[t] = s
                        heapq.heappush(heap, (c + self.bend, t))
        return found, pred

    def _nodes_of_path(self, s, pred):
        nodes = []
        while True:
            n = s // 4
            if not nodes or nodes[-1] != n:
                nodes.append(n)
            if s not in pred:
                break
            s = pred[s]
        nodes.reverse()
        return nodes

    def _to_polyline(self, nodes):
        pts = [self.xy(n) for n in nodes]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            a, b, c = out[-1], pts[k], pts[k + 1]
            same_x = abs(a[0] - b[0]) < 1e-9 and abs(b[0] - c[0]) < 1e-9
            same_y = abs(a[1] - b[1]) < 1e-9 and abs(b[1] - c[1]) < 1e-9
            if not (same_x or same_y):
                out.append(b)
        if len(pts) > 1:
            out.append(pts[-1])
        return out

    def _add_usage(self, usage, nodes):
        for a, b in zip(nodes, nodes[1:]):
            axis = 0 if abs(a - b) == 1 else 1
            key = (min(a, b), axis)
            usage.edge[key] = usage.edge.get(key, 0) + 1
            bit = 1 if axis == 0 else 2
            usage.node_axes[a] = usage.node_axes.get(a, 0) | bit
            usage.node_axes[b] = usage.node_axes.get(b, 0) | bit

    # ------------------------------------------------------------------ public API
    def distance_matrix(self, points):
        """Cheapest (length + 0.5 per bend) axis-aligned distance between all terminals; inf if cut off."""
        nodes = [self.node_of(p) for p in points]
        k = len(nodes)
        D = np.full((k, k), math.inf)
        for i, n in enumerate(nodes):
            found, _ = self._search(n, set(nodes))
            for j, m in enumerate(nodes):
                if m in found:
                    D[i, j] = found[m][0]
        D = np.minimum(D, D.T)
        np.fill_diagonal(D, 0.0)
        return D

    def route_ring(self, points, order, usage=None):
        """Legs for the closed ring points[order[0]] -> ... -> points[order[-1]] -> points[order[0]].

        Each leg is routed with the cable laid by earlier legs (and earlier rings) in view.
        Raises ValueError if a leg cannot be routed."""
        usage = usage if usage is not None else Usage()
        seq = list(order) + [order[0]]
        legs, prev_dir = [], None
        for a, b in zip(seq, seq[1:]):
            src, dst = self.node_of(points[a]), self.node_of(points[b])
            if src == dst:
                legs.append([self.xy(src), self.xy(dst)])
                continue
            found, pred = self._search(src, {dst}, prev_dir, usage)
            if dst not in found:
                raise ValueError(f"no door-connected route from {points[a]} to {points[b]}")
            _, s = found[dst]
            nodes = self._nodes_of_path(s, pred)
            self._add_usage(usage, nodes)
            legs.append(self._to_polyline(nodes))
            prev_dir = s % 4
        return legs


def inside_from_shapely(free_space):
    """Vectorised point-in-free-space test (needs shapely >= 2.0)."""
    from shapely import contains_xy
    return lambda x, y: contains_xy(free_space, x, y)
