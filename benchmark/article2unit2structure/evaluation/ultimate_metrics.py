"""Ultimate metrics (TES / SoftF1 / DefeaterRecall) for st2.v3 outputs.

This module is a self-contained (no SciPy) implementation of:
- TES (Tree-Edit Similarity): 1 - (tree-edit-distance / (|V_pred| + |V_gold|))
- SoftF1: max-weight matching by IoU, TP if IoU >= threshold
- DefeaterRecall: recall over defeater-like nodes (leaf tag "排除")

st2.v3 structured outputs do not provide byte offsets; we approximate spans by
substring search over whitespace-normalized `input_text = gold.rule_text + "\\n" + gold.unit_text`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Span = Optional[Tuple[int, int]]


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _find_nth(haystack: str, needle: str, n: int) -> int:
    if not needle:
        return -1
    pos = -1
    for _ in range(max(1, n)):
        pos = haystack.find(needle, pos + 1)
        if pos < 0:
            return -1
    return pos


def find_span_in_text(*, text: str, input_text: str, occurrence: Optional[int] = None) -> Span:
    """Return (start,end) on a whitespace-normalized `input_text`, or None if not found."""

    needle = _norm_ws(text)
    hay = _norm_ws(input_text)
    if not needle:
        return None

    occ = int(occurrence) if isinstance(occurrence, int) and occurrence >= 1 else 1
    start = _find_nth(hay, needle, occ)
    if start < 0:
        # Fallback: try the first occurrence even if occ is off.
        start = hay.find(needle)
    if start < 0:
        return None
    return (start, start + len(needle))


def _structural_span() -> Tuple[int, int]:
    # Non-span nodes should not be penalized by IoU-based rename cost.
    return (0, 1)


def _calculate_iou(span1: Span, span2: Span) -> float:
    """1D IoU for (start,end). Returns 0.0 if either span is None/invalid."""

    if not span1 or not span2:
        return 0.0
    s1, e1 = span1
    s2, e2 = span2
    inter_s, inter_e = max(s1, s2), min(e1, e2)
    if inter_e <= inter_s:
        return 0.0
    intersection = inter_e - inter_s
    union = (e1 - s1) + (e2 - s2) - intersection
    return (intersection / union) if union > 0 else 0.0


def _linear_sum_assignment_min(cost: Sequence[Sequence[float]]) -> Tuple[List[int], List[int]]:
    """Min-cost assignment for a rectangular cost matrix (pure Python Hungarian).

    Behavior matches scipy.optimize.linear_sum_assignment:
    - If n_rows <= n_cols: every row is assigned to one column -> len(row_ind)=n_rows
    - Else: every column is assigned to one row -> len(row_ind)=n_cols
    """

    n = len(cost)
    if n == 0:
        return [], []
    m = len(cost[0]) if cost[0] is not None else 0
    if m == 0:
        return [], []
    for row in cost:
        if len(row) != m:
            raise ValueError("cost matrix must be rectangular")

    # Hungarian implementation below assumes m >= n (more columns than rows).
    transposed = False
    if n > m:
        transposed = True
        cost_t = [[float(cost[i][j]) for i in range(n)] for j in range(m)]
        cost = cost_t
        n, m = m, n

    # 1-indexed arrays.
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)  # matched row for column j
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = float(cost[i0 - 1][j - 1]) - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    # Decode matching.
    row_to_col = [-1] * n
    for j in range(1, m + 1):
        if p[j] != 0:
            row_to_col[p[j] - 1] = j - 1

    if not transposed:
        row_ind = list(range(n))
        col_ind = [c for c in row_to_col if c != -1]
        # Every row should be assigned since m>=n.
        if len(col_ind) != n:
            # Defensive; shouldn't happen.
            row_ind = [i for i, c in enumerate(row_to_col) if c != -1]
            col_ind = [c for c in row_to_col if c != -1]
        return row_ind, col_ind

    # Invert for the original (n_orig > m_orig) case:
    # We solved on transposed matrix of shape (m_orig rows, n_orig cols).
    # row_to_col maps each original column -> original row.
    col_ind = list(range(n))  # n == m_orig (original column count)
    row_ind = [row_to_col[i] for i in range(n)]
    # Filter any unassigned (shouldn't happen).
    pairs = [(r, c) for r, c in zip(row_ind, col_ind) if r != -1]
    return [r for r, _c in pairs], [c for _r, c in pairs]


def _linear_sum_assignment_max(weight: Sequence[Sequence[float]]) -> Tuple[List[int], List[int]]:
    """Max-weight assignment via min-cost Hungarian (cost = max_w - w)."""

    n = len(weight)
    if n == 0:
        return [], []
    m = len(weight[0]) if weight[0] is not None else 0
    if m == 0:
        return [], []
    max_w = max(float(weight[i][j]) for i in range(n) for j in range(m))
    cost = [[max_w - float(weight[i][j]) for j in range(m)] for i in range(n)]
    return _linear_sum_assignment_min(cost)


def _build_tree(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a flat tree ({nodes, edges}) into a recursive tree for TED."""

    if not data or "nodes" not in data:
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return None
    nodes_map: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        if isinstance(nid, str) and nid:
            nodes_map[nid] = {**n, "children": []}
    if not nodes_map:
        return None

    children_ids: set[str] = set()
    for u, v in data.get("edges", []) or []:
        if u in nodes_map and v in nodes_map:
            nodes_map[u]["children"].append(nodes_map[v])
            children_ids.add(v)

    roots = [n for nid, n in nodes_map.items() if nid not in children_ids]
    if not roots:
        return None
    if len(roots) == 1:
        return roots[0]
    return {"id": "V_ROOT", "type": "ROOT", "span": (0, 0), "children": roots}


def _count_nodes(tree: Optional[Dict[str, Any]]) -> int:
    if tree is None:
        return 0
    c = 1
    for child in tree.get("children", []) or []:
        if isinstance(child, dict):
            c += _count_nodes(child)
    return c


def compute_tree_edit_sim(pred_data: Dict[str, Any], gold_data: Dict[str, Any], *, ignore_spans: bool = False) -> float:
    """TES: Tree-Edit Similarity in [0,1]."""

    t1 = _build_tree(pred_data)
    t2 = _build_tree(gold_data)
    if t1 is None and t2 is None:
        return 1.0
    if t1 is None or t2 is None:
        return 0.0

    memo: Dict[Tuple[str, str], float] = {}

    def ted(n1: Dict[str, Any], n2: Dict[str, Any]) -> float:
        k1 = str(n1.get("id") or "")
        k2 = str(n2.get("id") or "")
        key = (k1, k2)
        if key in memo:
            return memo[key]

        if n1.get("type") != n2.get("type"):
            node_cost = 1.0
        else:
            if ignore_spans:
                node_cost = 0.0
            else:
                node_cost = 1.0 - _calculate_iou(n1.get("span"), n2.get("span"))

        children1 = n1.get("children", []) or []
        children2 = n2.get("children", []) or []
        if not children1 and not children2:
            memo[key] = float(node_cost)
            return float(node_cost)

        c1 = [c for c in children1 if isinstance(c, dict)]
        c2 = [c for c in children2 if isinstance(c, dict)]

        match_cost = 0.0
        matched_rows: set[int] = set()
        matched_cols: set[int] = set()
        if c1 and c2:
            c_matrix = [[ted(a, b) for b in c2] for a in c1]
            row_ind, col_ind = _linear_sum_assignment_min(c_matrix)
            for r, c in zip(row_ind, col_ind):
                match_cost += float(c_matrix[r][c])
                matched_rows.add(int(r))
                matched_cols.add(int(c))

        del_cost = sum(_count_nodes(c1[i]) for i in range(len(c1)) if i not in matched_rows)
        ins_cost = sum(_count_nodes(c2[j]) for j in range(len(c2)) if j not in matched_cols)

        total_cost = float(node_cost) + float(match_cost) + float(del_cost) + float(ins_cost)
        memo[key] = total_cost
        return total_cost

    distance = ted(t1, t2)
    max_dist = _count_nodes(t1) + _count_nodes(t2)
    if max_dist <= 0:
        return 1.0
    return max(0.0, 1.0 - (distance / max_dist))


def compute_soft_span_f1(pred_nodes: Sequence[Dict[str, Any]], gold_nodes: Sequence[Dict[str, Any]], *, iou_threshold: float = 0.8) -> float:
    """SoftF1 in [0,1] on span-bearing nodes."""

    pnodes = [n for n in pred_nodes if isinstance(n, dict)]
    gnodes = [n for n in gold_nodes if isinstance(n, dict)]
    if not pnodes and not gnodes:
        return 1.0
    if not pnodes or not gnodes:
        return 0.0

    weights: List[List[float]] = []
    for p in pnodes:
        prow: List[float] = []
        for g in gnodes:
            if p.get("type") == g.get("type"):
                prow.append(_calculate_iou(p.get("span"), g.get("span")))
            else:
                prow.append(0.0)
        weights.append(prow)

    row_ind, col_ind = _linear_sum_assignment_max(weights)
    tp = 0
    for r, c in zip(row_ind, col_ind):
        if float(weights[r][c]) >= float(iou_threshold):
            tp += 1
    p = tp / len(pnodes)
    r = tp / len(gnodes)
    return float((2 * p * r) / (p + r + 1e-9))


def compute_defeater_recall(
    pred_nodes: Sequence[Dict[str, Any]],
    gold_nodes: Sequence[Dict[str, Any]],
    *,
    iou_threshold: float = 0.8,
    defeater_types: Optional[set[str]] = None,
) -> float:
    """Recall over defeater-like nodes. Returns 1.0 if no gold defeaters exist."""

    base = {
        "Defeater",
        "Exception",
        "Counter-Exception",
        "Exclusion",
        "Proviso",
        "Limit",
    }
    if defeater_types:
        base |= {str(x) for x in defeater_types if str(x)}
    # Leaf nodes tagged as "排除" are treated as defeaters/exclusions in SG-DT.
    base.add("排除")

    g_defs = [n for n in gold_nodes if isinstance(n, dict) and n.get("type") in base]
    p_defs = [n for n in pred_nodes if isinstance(n, dict) and n.get("type") in base]

    if not g_defs:
        return 1.0
    if not p_defs:
        return 0.0

    weights: List[List[float]] = []
    for p in p_defs:
        prow: List[float] = []
        for g in g_defs:
            if p.get("type") == g.get("type"):
                prow.append(_calculate_iou(p.get("span"), g.get("span")))
            else:
                prow.append(0.0)
        weights.append(prow)

    row_ind, col_ind = _linear_sum_assignment_max(weights)
    tp = 0
    for r, c in zip(row_ind, col_ind):
        if float(weights[r][c]) >= float(iou_threshold):
            tp += 1
    return float(tp / len(g_defs))


@dataclass(frozen=True)
class FlatTree:
    tree: Dict[str, Any]  # {'nodes': [...], 'edges': [(u,v), ...]}
    span_nodes: List[Dict[str, Any]]  # subset used for SoftF1/DefRecall
    defeater_nodes: List[Dict[str, Any]]  # subset of span_nodes with type in defeater_types


def structured_to_flat_tree(structured: Dict[str, Any], *, input_text: str) -> FlatTree:
    """Convert Task1 Stage2 `structured` dict into LogiLaw-style flat tree with spans."""

    nodes: List[Dict[str, Any]] = []
    edges: List[Tuple[str, str]] = []
    span_nodes: List[Dict[str, Any]] = []

    defeater_type_set = {
        "Defeater",
        "Exception",
        "Counter-Exception",
        "Exclusion",
        "Proviso",
        "Limit",
        "排除",
    }

    next_id = 0

    def nid(prefix: str) -> str:
        nonlocal next_id
        next_id += 1
        return f"{prefix}{next_id}"

    def add_node(*, node_type: str, span: Span, extra: Optional[Dict[str, Any]] = None) -> str:
        node_id = nid("n")
        d: Dict[str, Any] = {"id": node_id, "type": node_type, "span": span}
        if extra:
            d.update(extra)
        nodes.append(d)
        return node_id

    root_id = add_node(node_type="ROOT", span=_structural_span())

    branches = structured.get("branches") if isinstance(structured.get("branches"), list) else []
    for b_i, b in enumerate(branches):
        if not isinstance(b, dict):
            continue

        anch = b.get("anchor")
        anch_text = anch.get("text") if isinstance(anch, dict) else ""
        anch_occ = anch.get("occurrence") if isinstance(anch, dict) else None
        anch_span = find_span_in_text(text=str(anch_text or ""), input_text=input_text, occurrence=anch_occ)
        anch_id = add_node(
            node_type="ANCH",
            span=anch_span,
            extra={"text": str(anch_text or ""), "occurrence": anch_occ, "branch_idx": b_i},
        )
        edges.append((root_id, anch_id))
        if anch_span is not None:
            span_nodes.append(nodes[-1])

        modal = b.get("norm_kind")
        modal_id = add_node(node_type=f"MODAL:{str(modal or '').strip()}", span=_structural_span())
        edges.append((anch_id, modal_id))

        def add_leaf(parent_id: str, leaf: Dict[str, Any]) -> None:
            tag = str(leaf.get("tag", "") or "")
            text = str(leaf.get("text", "") or "")
            sp = find_span_in_text(text=text, input_text=input_text)
            leaf_id = add_node(node_type=tag, span=sp, extra={"text": text, "tag": tag})
            edges.append((parent_id, leaf_id))
            if sp is not None:
                span_nodes.append(nodes[-1])

        def add_cond(parent_id: str, cond: Any) -> None:
            if not isinstance(cond, dict):
                return
            if "op" in cond and "items" in cond:
                op = str(cond.get("op", "")).upper()
                op_id = add_node(node_type=f"OP:{op}", span=_structural_span())
                edges.append((parent_id, op_id))
                for it in cond.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    if "op" in it and "items" in it:
                        add_cond(op_id, it)
                    else:
                        add_leaf(op_id, it)
                return
            add_leaf(parent_id, cond)

        cond = b.get("conditions")
        if isinstance(cond, dict):
            add_cond(modal_id, cond)

        effects = b.get("effects") if isinstance(b.get("effects"), list) else []
        for eff in effects:
            if not isinstance(eff, dict):
                continue
            et = str(eff.get("effect_text", "") or "")
            sp = find_span_in_text(text=et, input_text=input_text)
            eff_id = add_node(node_type="EFFECT", span=sp, extra={"effect_text": et})
            edges.append((anch_id, eff_id))
            if sp is not None:
                span_nodes.append(nodes[-1])

    defeater_nodes = [n for n in span_nodes if n.get("type") in defeater_type_set]
    return FlatTree(tree={"nodes": nodes, "edges": edges}, span_nodes=span_nodes, defeater_nodes=defeater_nodes)
