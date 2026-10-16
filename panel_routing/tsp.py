"""Closed-tour solver for ONE panel.

Node 0 is the panel, nodes 1..n-1 are its devices. D is a symmetric (n x n)
matrix of real path distances (not straight-line), so the tour respects walls.
A panel has at most 21 nodes, so exact search for tiny cases and multi-start
2-opt + Or-opt for the rest is effectively optimal and fast.
"""
import itertools
import random

import numpy as np


def tour_length(order, D):
    n = len(order)
    return float(sum(D[order[i], order[(i + 1) % n]] for i in range(n)))


def nearest_neighbor(D):
    n = len(D)
    order = [0]
    left = set(range(1, n))
    while left:
        last = order[-1]
        nxt = min(left, key=lambda j: (D[last, j], j))
        order.append(nxt)
        left.remove(nxt)
    return order


def two_opt(order, D):
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = order[i - 1], order[i]
                c, d = order[j], order[(j + 1) % n]
                if D[a, c] + D[b, d] - D[a, b] - D[c, d] < -1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
    return order


def or_opt(order, D, max_seg=3):
    """Move segments of 1..max_seg nodes (optionally reversed) to a better spot."""
    n = len(order)
    improved = True
    while improved:
        improved = False
        for seg in range(1, max_seg + 1):
            if seg >= n - 1:
                break
            for i in range(1, n - seg + 1):
                segment = order[i:i + seg]
                prev, nxt = order[i - 1], order[(i + seg) % n]
                remove_gain = D[prev, segment[0]] + D[segment[-1], nxt] - D[prev, nxt]
                rest = order[:i] + order[i + seg:]
                m = len(rest)
                best_gain, best_k, best_rev = 1e-9, None, False
                for k in range(m):
                    p, q = rest[k], rest[(k + 1) % m]
                    for rev in (False, True):
                        s0, s1 = (segment[-1], segment[0]) if rev else (segment[0], segment[-1])
                        gain = remove_gain - (D[p, s0] + D[s1, q] - D[p, q])
                        if gain > best_gain:
                            best_gain, best_k, best_rev = gain, k, rev
                if best_k is not None:
                    ins = segment[::-1] if best_rev else segment
                    order = rest[:best_k + 1] + ins + rest[best_k + 1:]
                    improved = True
                    break
            if improved:
                break
    return order


def solve_tour(D, seed=0, restarts=20):
    """Return a visiting order [0, ...] (each node once; the tour closes back to 0)."""
    D = np.asarray(D, dtype=float)
    n = len(D)
    if n <= 3:
        return list(range(n))
    if n <= 9:  # exact: at most 8! = 40320 permutations
        best = min(itertools.permutations(range(1, n)),
                   key=lambda p: tour_length([0, *p], D))
        return [0, *best]
    rng = random.Random(seed)
    candidates = [nearest_neighbor(D)]
    for _ in range(restarts):
        p = list(range(1, n))
        rng.shuffle(p)
        candidates.append([0, *p])
    best_len, best_order = None, None
    for c in candidates:
        c = two_opt(list(c), D)
        c = or_opt(c, D)
        c = two_opt(c, D)
        length = tour_length(c, D)
        if best_len is None or length < best_len - 1e-9:
            best_len, best_order = length, c
    return best_order
