"""Skeleton graph of a rasterised glyph, stroke tracing and stroke width profiles.

    from mapotofu.tools.raster import FontSource
    from mapotofu.tools.skeleton import SkelGraph

    glyph = FontSource("Font.otf").glyph("永")
    graph = SkelGraph(glyph.ink)             # nodes, edges, graph.dt (half stroke widths, pixels)
    pixels, in_junction, nodes = graph.trace_from(end_node)

Pipeline for one glyph:
  ink --skeletonize--> 1-px centre lines; distance transform gives half the stroke width.
  Short spurs (corners of flat terminals) are pruned.
  The skeleton becomes a graph: nodes are endpoints and junction clusters, edges are the
  pixel chains between them.
  A *stroke* is traced from a free endpoint by walking edge to edge through junctions,
  always taking the branch that continues most straight (and only when that continuation
  bends less than MAX_TURN). This follows a 撇 through the horizontal it crosses in 大, but
  stops a 捺 where it leaves the 撇 in 人.
  Samples close to a junction are flagged: there the inscribed circle covers two strokes
  and the width is meaningless.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import convolve, distance_transform_edt, label, map_coordinates
from skimage.morphology import skeletonize

K8 = np.ones((3, 3), int)
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
MAX_TURN = 38.0      # degrees allowed when continuing a stroke through a junction
SPUR_K = 1.6         # terminal edges shorter than SPUR_K * junction radius are pruned
JUNCTION_K = 1.25    # samples within JUNCTION_K * junction radius of a junction are masked


class Edge:
    __slots__ = ("pix", "a", "b", "length")

    def __init__(self, pix, a, b):
        self.pix = pix          # (n, 2) int array of (row, col), from node a to node b
        self.a, self.b = a, b   # node ids
        d = np.diff(pix, axis=0)
        self.length = float(np.hypot(d[:, 0], d[:, 1]).sum()) if len(pix) > 1 else 0.0


class SkelGraph:
    """The skeleton of a glyph's ink (bool array, row 0 at the top) as a graph.

    node_kind[i] is "end" or "junction", node_center[i] its (row, col), node_r[i] the inscribed
    radius there; edges are Edge objects (pixel chains between two nodes), adj[i] the edges at
    node i; sk is the skeleton image and dt the distance transform of the ink (half the stroke
    width at a skeleton pixel, in pixels). spur_k, junction_k and max_turn replace the module's
    SPUR_K, JUNCTION_K and MAX_TURN."""

    def __init__(self, ink, prune_rounds=4, spur_k=SPUR_K, junction_k=JUNCTION_K, max_turn=MAX_TURN):
        self.ink = ink
        self.junction_k, self.max_turn = junction_k, max_turn
        self.dt = distance_transform_edt(ink)
        sk = skeletonize(ink)
        for _ in range(prune_rounds):
            self._build(sk)
            removed = False
            for e in self.edges:
                ends = [self.node_kind[e.a], self.node_kind[e.b]]
                if ends.count("end") == 1 and "junction" in ends:
                    j = e.a if self.node_kind[e.a] == "junction" else e.b
                    if e.length < spur_k * self.node_r[j]:
                        keep = self.node_pix_set[j]
                        for r, c in e.pix:
                            if (r, c) not in keep:
                                sk[r, c] = False
                        removed = True
            if not removed:
                break
            sk = skeletonize(sk)
        self.sk = sk
        self._build(sk)

    # -------------------------------------------------------------- graph construction
    def _build(self, sk):
        deg = convolve(sk.astype(int), K8, mode="constant") - 1
        deg[~sk] = 0
        jmask = sk & (deg >= 3)
        jlab, nj = label(jmask, structure=np.ones((3, 3)))
        node_of = -np.ones(sk.shape, int)
        self.node_kind, self.node_r, self.node_pix_set, self.node_center = [], [], [], []
        for j in range(1, nj + 1):
            pts = np.argwhere(jlab == j)
            nid = len(self.node_kind)
            node_of[pts[:, 0], pts[:, 1]] = nid
            self.node_kind.append("junction")
            self.node_r.append(float(self.dt[pts[:, 0], pts[:, 1]].max()))
            self.node_pix_set.append({tuple(p) for p in pts})
            self.node_center.append(pts.mean(0))
        for p in np.argwhere(sk & (deg <= 1)):
            nid = len(self.node_kind)
            node_of[p[0], p[1]] = nid
            self.node_kind.append("end")
            self.node_r.append(float(self.dt[p[0], p[1]]))
            self.node_pix_set.append({tuple(p)})
            self.node_center.append(p.astype(float))
        self.node_of = node_of
        H, W = sk.shape
        visited = np.zeros(sk.shape, bool)
        edges, seen_pairs = [], set()
        for nid, pix in enumerate(self.node_pix_set):
            for (r, c) in pix:
                for dr, dc in NB:
                    r2, c2 = r + dr, c + dc
                    if not (0 <= r2 < H and 0 <= c2 < W) or not sk[r2, c2]:
                        continue
                    if node_of[r2, c2] == nid:
                        continue
                    if node_of[r2, c2] >= 0:      # two nodes directly adjacent
                        key = (min(nid, node_of[r2, c2]), max(nid, node_of[r2, c2]), r, c, r2, c2)
                        pk = (min(nid, node_of[r2, c2]), max(nid, node_of[r2, c2]))
                        if pk in seen_pairs:
                            continue
                        seen_pairs.add(pk)
                        edges.append(Edge(np.array([(r, c), (r2, c2)]), nid, node_of[r2, c2]))
                        continue
                    if visited[r2, c2]:
                        continue
                    path = [(r, c), (r2, c2)]
                    visited[r2, c2] = True
                    prev, cur = (r, c), (r2, c2)
                    end = None
                    while True:
                        nxt = None
                        for er, ec in NB:
                            q = (cur[0] + er, cur[1] + ec)
                            if q == prev or not (0 <= q[0] < H and 0 <= q[1] < W) or not sk[q]:
                                continue
                            if node_of[q] >= 0 and node_of[q] != -1:
                                if node_of[q] == nid and len(path) <= 2:
                                    continue
                                end = node_of[q]
                                nxt = q
                                break
                            if not visited[q]:
                                nxt = q
                        if nxt is None:
                            break
                        path.append(nxt)
                        if end is not None:
                            break
                        visited[nxt] = True
                        prev, cur = cur, nxt
                    if end is None:
                        continue  # loop without node; ignore
                    edges.append(Edge(np.array(path), nid, end))
        self.edges = self._merge_close_junctions(edges)
        self.adj = [[] for _ in self.node_kind]
        for i, e in enumerate(self.edges):
            self.adj[e.a].append(i)
            if e.b != e.a:
                self.adj[e.b].append(i)

    def _merge_close_junctions(self, edges):
        """Thinning turns an X crossing into two Y junctions joined by a short edge (and a
        thick junction into several). Merge junctions joined by edges shorter than their
        radius so a crossing becomes one node."""
        parent = list(range(len(self.node_kind)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        short = []
        for i, e in enumerate(edges):
            if (e.a != e.b and self.node_kind[e.a] == "junction" == self.node_kind[e.b]
                    and e.length < 1.1 * max(self.node_r[e.a], self.node_r[e.b])):
                parent[find(e.a)] = find(e.b)
                short.append(i)
        if not short:
            return edges
        groups = {}
        for n in range(len(parent)):
            groups.setdefault(find(n), []).append(n)
        for root, members in groups.items():
            if len(members) < 2:
                continue
            pix = set().union(*(self.node_pix_set[m] for m in members))
            for (r, c) in pix:
                self.node_of[r, c] = root
            self.node_pix_set[root] = pix
            self.node_r[root] = max(self.node_r[m] for m in members)
            self.node_center[root] = np.mean([self.node_center[m] for m in members], 0)
            for m in members:
                if m != root:
                    self.node_kind[m] = "merged"
        drop = set(short)
        out = []
        for i, e in enumerate(edges):
            if i in drop:
                continue
            a, b = find(e.a), find(e.b)
            if a == b and self.node_kind[a] == "junction" and e.length < 2 * self.node_r[a]:
                continue
            out.append(Edge(e.pix, a, b))
        return out

    # -------------------------------------------------------------- helpers
    def oriented(self, ei, from_node):
        e = self.edges[ei]
        return e.pix if e.a == from_node else e.pix[::-1]

    def leave_dir(self, ei, node):
        """Unit direction (drow, dcol) of edge ei as it leaves `node`, measured beyond the
        junction's distortion zone."""
        pix = self.oriented(ei, node).astype(float)
        seg = np.hypot(*np.diff(pix, axis=0).T)
        s = np.concatenate([[0], np.cumsum(seg)])
        r = self.node_r[node]
        a = min(1.0 * r, s[-1] * 0.4)
        b = min(a + max(2.0 * r, 10.0), s[-1])
        if b - a < 2:
            a, b = 0, s[-1]
        pa = np.array([np.interp(a, s, pix[:, 0]), np.interp(a, s, pix[:, 1])])
        pb = np.array([np.interp(b, s, pix[:, 0]), np.interp(b, s, pix[:, 1])])
        v = pb - pa
        n = np.hypot(*v)
        return v / n if n > 0 else v

    def trace_from(self, end_node):
        """Trace a stroke from a free endpoint. Returns (pixels, junction_mask, node_list)."""
        if self.node_kind[end_node] != "end" or not self.adj[end_node]:
            return None
        cur_node, ei = end_node, self.adj[end_node][0]
        chain, mask, nodes, used = [], [], [end_node], {ei}
        while True:
            pix = self.oriented(ei, cur_node)
            nxt_node = self.edges[ei].b if self.edges[ei].a == cur_node else self.edges[ei].a
            chain.append(pix if not chain else pix[1:])
            nodes.append(nxt_node)
            if self.node_kind[nxt_node] != "junction":
                break
            arrive = -self.leave_dir(ei, nxt_node)
            best, best_cos = None, -2
            for ej in self.adj[nxt_node]:
                if ej in used:
                    continue
                c = float(np.dot(arrive, self.leave_dir(ej, nxt_node)))
                if c > best_cos:
                    best, best_cos = ej, c
            if best is None or best_cos < math.cos(math.radians(self.max_turn)):
                break
            # the continuation must also be the best match seen from the other side
            back = -self.leave_dir(best, nxt_node)
            rival = max((float(np.dot(back, self.leave_dir(ej, nxt_node))), ej)
                        for ej in self.adj[nxt_node] if ej != best)
            if rival[1] != ei:
                break
            used.add(best)
            cur_node, ei = nxt_node, best
        pix = np.vstack(chain)
        # junction mask
        m = np.zeros(len(pix), bool)
        for n in nodes:
            if self.node_kind[n] == "junction":
                d = np.hypot(*(pix - self.node_center[n]).T)
                m |= d < self.junction_k * self.node_r[n] + 1.5
        return pix, m, nodes

    def body_mask(self):
        """Skeleton pixels away from every junction (for global width statistics)."""
        pts = np.argwhere(self.sk)
        m = np.ones(len(pts), bool)
        for n, kind in enumerate(self.node_kind):
            if kind == "junction":
                d = np.hypot(*(pts - self.node_center[n]).T)
                m &= d >= self.junction_k * self.node_r[n] + 1.5
        return pts, m


def cross_section(ink, p, u, d, half_len):
    """Ink length along the line through p + d*u perpendicular to u (pixels)."""
    n = np.array([-u[1], u[0]])
    t = np.arange(-half_len, half_len + 0.5, 0.5)
    q = p[None, :] + d * u[None, :] + t[:, None] * n[None, :]
    v = map_coordinates(ink.astype(float), q.T, order=1, mode="constant")
    # contiguous run through the centre
    c = len(t) // 2
    if v[c] < 0.5:
        return 0.0
    lo = c
    while lo > 0 and v[lo - 1] >= 0.5:
        lo -= 1
    hi = c
    while hi < len(v) - 1 and v[hi + 1] >= 0.5:
        hi += 1
    return (hi - lo + 1) * 0.5


def terminal_shape(ink, pix, width_px):
    """Describe how a stroke ends. pix runs from the stroke body to the free end.

    Returns cap = distance from the outermost ink point back to where the cross-section
    first reaches 90 % of the local stroke width, in units of that width:
      ~0 flat/square end,  ~0.28 semicircular (round) end,  > 0.5 tapered/pointed end.
    """
    if len(pix) < 6 or width_px < 2:
        return np.nan
    pts = pix.astype(float)
    k = min(len(pts) - 1, max(4, int(2.0 * width_px)))
    u = pts[-1] - pts[-1 - k]
    nu = np.hypot(*u)
    if nu == 0:
        return np.nan
    u /= nu
    # walk outward from the skeleton end to the last ink pixel along u
    tip = pts[-1].copy()
    for _ in range(int(3 * width_px) + 5):
        q = tip + 0.5 * u
        if map_coordinates(ink.astype(float), q[:, None], order=1)[0] < 0.5:
            break
        tip = q
    # local stroke width one width back from the tip (a tapered stroke is thinner here
    # than its median, so the median would make every taper look endless)
    ref_w = cross_section(ink, tip, -u, 1.2 * width_px, 2 * width_px)
    if ref_w < 1:
        return np.nan
    for d in np.arange(0, 1.2 * width_px, 0.5):
        w = cross_section(ink, tip, -u, d, 2 * width_px)
        if w >= 0.9 * ref_w:
            return d / ref_w
    return 1.2 * width_px / ref_w


def tail_roundness(ink, pix, width_px):
    """How far the free end of a stroke is from a clean round end. pix runs from the stroke body
    to the free end, width_px is the body's width (pixels).

    The axis is fitted on the skeleton 1.5 to 3.5 widths back from the end; the stroke's own ink
    ahead of that is taken across the axis (the run through the axis at each step along it). The
    cap is the ink beyond the cross-section x before the farthest ink whose half width is x (the
    radius r of a half disc). Returns the area of its symmetric difference with the half disc of
    radius r on that cross-section's centre, over the half disc's area: about 0.05 for the round
    ends of a rounded gothic, 0.27 for a square end, more for a slanted brush foot or a tail."""
    if len(pix) < 6 or width_px < 2:
        return np.nan
    pts = pix.astype(float)
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    back = s[-1] - s
    sel = (back >= 1.5 * width_px) & (back <= 3.5 * width_px)
    if sel.sum() < 4:
        return np.nan
    q0 = pts[sel].mean(0)
    u = np.linalg.svd(pts[sel] - q0)[2][0]
    if (pts[-1] - q0) @ u < 0:
        u = -u
    n = np.array([-u[1], u[0]])
    X = np.argwhere(ink).astype(float) - q0
    a, b = X @ u, X @ n
    near = (a > 0) & (a < 4 * width_px) & (np.abs(b) < 1.6 * width_px)
    a, b = a[near], b[near]
    if len(a) < 10:
        return np.nan
    ab = np.round(a).astype(int)
    keep = np.zeros(len(a), bool)
    for k in np.unique(ab):
        m = np.flatnonzero(ab == k)
        o = np.argsort(b[m])
        bb = b[m][o]
        j = int(np.argmin(np.abs(bb)))
        if abs(bb[j]) > 0.8 * width_px:
            continue
        lo = hi = j
        while lo > 0 and bb[lo] - bb[lo - 1] <= 1.5:
            lo -= 1
        while hi < len(bb) - 1 and bb[hi + 1] - bb[hi] <= 1.5:
            hi += 1
        keep[m[o[lo:hi + 1]]] = True
    a, b = a[keep], b[keep]
    if not len(a):
        return np.nan
    tip = a.max()

    def half(x):
        m = np.abs(a - (tip - x)) < 1
        return 0.5 * (b[m].max() - b[m].min() + 1) if m.sum() >= 2 else 0.0

    x = 1.0
    while x < 2 * width_px and half(x) > x:
        x += 0.5
    cs = np.abs(a - (tip - x)) < 1
    if cs.sum() < 2:
        return np.nan
    b0, r = 0.5 * (b[cs].min() + b[cs].max()), x
    cap = a >= tip - x
    disc = np.hypot(a[cap] - (tip - x), b[cap] - b0) <= r
    area = math.pi * r * r / 2
    return float(((~disc).sum() + max(area - disc.sum(), 0)) / area)


def resample_profile(s, w, mask, n=41):
    """Resample a width profile w(s) onto n points over t = s/s_max in [0, 1];
    masked samples are dropped and the gaps interpolated (NaN if too little data)."""
    ok = ~mask
    if ok.sum() < 5:
        return None
    t = s / s[-1]
    tt = np.linspace(0, 1, n)
    prof = np.interp(tt, t[ok], w[ok])
    # mark points far from any valid sample as NaN (inside long masked stretches)
    gap = np.min(np.abs(tt[:, None] - t[ok][None, :]), axis=1)
    prof[gap > 0.08] = np.nan
    return prof
