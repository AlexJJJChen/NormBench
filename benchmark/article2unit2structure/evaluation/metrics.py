"""Metrics for st2.v3 structured outputs (SG-DT recovery).

Implements paper-style structural metrics:
- NodeSpan-F1 (span-bearing nodes)
- Edge-F1
- Tree-EM
- nTED (normalized edit distance)
- SpanFaith / Halluc (span auditability proxies)

Strict scoring: invalid predictions receive structure scores of 0.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _norm_text(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324 - non-crypto use (stable signature)


Edge = Tuple[str, str, str]


@dataclass(frozen=True)
class Graph:
    nodes: Set[str]
    edges: Set[Edge]


def _leaf_sig(leaf: Dict[str, Any]) -> str:
    return f"LEAF|{_norm_text(str(leaf.get('tag', '')))}|{_norm_text(str(leaf.get('text', '')))}"


def _effect_sig(effect: Dict[str, Any]) -> str:
    return f"EFFECT|{_norm_text(str(effect.get('effect_text', '')))}"


def _anchor_sig(anchor: Any) -> str:
    if not isinstance(anchor, dict):
        return "ANCH||0"
    text = _norm_text(str(anchor.get("text", "")))
    occ = anchor.get("occurrence")
    occ_s = str(occ) if isinstance(occ, int) else "0"
    return f"ANCH|{text}|{occ_s}"


def _modality_sig(norm_kind: Any) -> str:
    # The paper refers to modality kappa; our schema uses norm_kind (e.g., obligation/permission/prohibition).
    return f"MODAL|{_norm_text(str(norm_kind or ''))}"


def _op_sig(node: Dict[str, Any]) -> str:
    op = str(node.get("op", "")).upper()
    items = node.get("items") or []
    child_sigs: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if "op" in it and "items" in it:
            child_sigs.append(_op_sig(it))
        else:
            child_sigs.append(_leaf_sig(it))
    key = op + "\n" + "\n".join(sorted(child_sigs))
    return f"OP|{op}|{_sha1(key)}"


def _collect_condition_graph(
    node: Dict[str, Any],
    *,
    nodes: Set[str],
    edges: Set[Edge],
) -> str:
    """Collect nodes/edges for the condition tree, return root signature."""

    root_sig = _op_sig(node)
    nodes.add(root_sig)
    items = node.get("items") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        if "op" in it and "items" in it:
            child_root = _collect_condition_graph(it, nodes=nodes, edges=edges)
            edges.add(("COND_CHILD", root_sig, child_root))
        else:
            leaf = _leaf_sig(it)
            nodes.add(leaf)
            edges.add(("COND_CHILD", root_sig, leaf))
    return root_sig


def build_graph(obj: Dict[str, Any]) -> Graph:
    """Build a canonical graph from a Stage2 structured output (parsed JSON dict)."""

    nodes: Set[str] = set()
    edges: Set[Edge] = set()

    branches = obj.get("branches")
    if not isinstance(branches, list):
        return Graph(nodes=set(), edges=set())

    for b in branches:
        if not isinstance(b, dict):
            continue
        cond = b.get("conditions")
        if not isinstance(cond, dict):
            continue

        # Anchor + modality (paper: alpha + kappa)
        anch = _anchor_sig(b.get("anchor"))
        modal = _modality_sig(b.get("norm_kind"))
        nodes.add(anch)
        nodes.add(modal)
        edges.add(("MOD", anch, modal))

        # Condition tree
        cond_root_sig = _collect_condition_graph(cond, nodes=nodes, edges=edges)
        # Tie the condition tree to the branch via modality. Without this, the unioned edge set can
        # ambiguously merge identical condition subtrees across branches.
        edges.add(("COND_ROOT", modal, cond_root_sig))

        # Effects
        effects = b.get("effects") if isinstance(b.get("effects"), list) else []
        for eff in effects:
            if not isinstance(eff, dict):
                continue
            sig = _effect_sig(eff)
            nodes.add(sig)
            edges.add(("ANCH_EFFECT", anch, sig))

    return Graph(nodes=nodes, edges=edges)


@dataclass(frozen=True)
class EdgeF1:
    precision: float
    recall: float
    f1: float
    tp: int
    pred_edges: int
    gold_edges: int


def edge_f1(gold_edges: Iterable[Edge], pred_edges: Iterable[Edge]) -> EdgeF1:
    gold_set = set(gold_edges)
    pred_set = set(pred_edges)
    inter = gold_set & pred_set

    tp = len(inter)
    pe = len(pred_set)
    ge = len(gold_set)

    if pe == 0:
        precision = 1.0 if ge == 0 else 0.0
    else:
        precision = tp / pe

    recall = 1.0 if ge == 0 else (tp / ge)

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return EdgeF1(
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        pred_edges=pe,
        gold_edges=ge,
    )


def tree_em(gold: Graph, pred: Graph) -> float:
    return 1.0 if (gold.nodes == pred.nodes and gold.edges == pred.edges) else 0.0


@dataclass(frozen=True)
class NodeF1:
    precision: float
    recall: float
    f1: float
    tp: int
    pred: int
    gold: int


def _is_span_node(sig: str) -> bool:
    # Span-bearing nodes in our canonicalization.
    return sig.startswith("LEAF|") or sig.startswith("EFFECT|")


def node_span_f1(gold_nodes: Iterable[str], pred_nodes: Iterable[str]) -> NodeF1:
    """NodeSpan-F1 analogue for Stage2: F1 on span-bearing node signatures.

    The paper keys nodes by (label, start, end). Stage2 does not expose byte offsets,
    so we approximate with deterministic node signatures (tag/text for leaves, effect_text for effects).
    """

    gold_set = {n for n in set(gold_nodes) if _is_span_node(n)}
    pred_set = {n for n in set(pred_nodes) if _is_span_node(n)}
    inter = gold_set & pred_set

    tp = len(inter)
    pn = len(pred_set)
    gn = len(gold_set)

    if pn == 0:
        precision = 1.0 if gn == 0 else 0.0
    else:
        precision = tp / pn

    recall = 1.0 if gn == 0 else (tp / gn)

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return NodeF1(precision=float(precision), recall=float(recall), f1=float(f1), tp=tp, pred=pn, gold=gn)


def nted(gold: Graph, pred: Graph) -> float:
    """Normalized edit distance on labeled nodes+edges (nTED).

    We approximate tree edit distance by counting set edits under exact signature matching:
    - Node edits: symmetric difference of node signatures
    - Edge edits: symmetric difference of labeled edges
    nTED is bounded in [0,1] by normalizing with the maximum possible set-edit cost:
      nTED = (NodeEdits + EdgeEdits) / (|V_gold| + |E_gold| + |V_pred| + |E_pred|).
    """

    node_edits = len(gold.nodes ^ pred.nodes)
    edge_edits = len(gold.edges ^ pred.edges)
    denom = max(1, len(gold.nodes) + len(gold.edges) + len(pred.nodes) + len(pred.edges))
    return float((node_edits + edge_edits) / denom)


def _iter_span_texts(obj: Dict[str, Any]) -> Iterable[str]:
    branches = obj.get("branches")
    if not isinstance(branches, list):
        return
    for b in branches:
        if not isinstance(b, dict):
            continue
        cond = b.get("conditions")
        yield from _iter_condition_leaf_texts(cond)
        effects = b.get("effects") if isinstance(b.get("effects"), list) else []
        for eff in effects:
            if isinstance(eff, dict) and isinstance(eff.get("effect_text"), str):
                yield eff["effect_text"]


def _iter_condition_leaf_texts(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        if "leaf_id" in node and "tag" in node and "text" in node:
            if isinstance(node.get("text"), str):
                yield node["text"]
            return
        for v in node.values():
            yield from _iter_condition_leaf_texts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_condition_leaf_texts(v)


def span_audit_metrics(pred_obj: Dict[str, Any], *, input_text: str) -> Tuple[float, float]:
    """Compute SpanFaith and Halluc rates from predicted texts.

    - SpanFaith: fraction of predicted span texts that appear (as a substring, whitespace-normalized)
      in the input provision text.
    - Halluc: fraction of predicted span texts that do NOT appear in the input provision text.
    """

    in_norm = _norm_text(input_text or "")
    texts = [t for t in _iter_span_texts(pred_obj) if isinstance(t, str)]
    if not texts:
        return 0.0, 0.0

    faithful = 0
    for t in texts:
        t_norm = _norm_text(t)
        if not t_norm:
            continue
        if t_norm in in_norm:
            faithful += 1
    total = len(texts)
    span_faith = faithful / total if total else 0.0
    halluc = (total - faithful) / total if total else 0.0
    return float(span_faith), float(halluc)
