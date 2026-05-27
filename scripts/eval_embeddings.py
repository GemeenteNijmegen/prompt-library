#!/usr/bin/env python3
"""Evaluate embedding retrieval quality across (model, source_strategy) variants.

Reads the corpus from the configured database (read-only), embeds each prompt
in memory under each variant, then scores probe queries from a YAML file.

Usage:
    python scripts/eval_embeddings.py [--probes PATH] [--summary-only]
"""
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source-strategy helpers
# ---------------------------------------------------------------------------

def _dedup(parts: list[str]) -> list[str]:
    """Remove duplicate strings while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def strategy_title(title: str, description: str, prompt_text: str) -> str:
    return title


def strategy_title_desc(title: str, description: str, prompt_text: str) -> str:
    return f"{title}\n\n{description}"


def strategy_full(title: str, description: str, prompt_text: str) -> str:
    return f"{title}\n\n{description}\n\n{prompt_text}"


def strategy_weighted(title: str, description: str, prompt_text: str) -> str:
    return f"{title}\n{title}\n{title}\n\n{description}\n\n{prompt_text}"


def strategy_full_dedup(title: str, description: str, prompt_text: str) -> str:
    parts = _dedup([title, description, prompt_text])
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Variant config — add rows here to test new (model, strategy) combinations
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    label: str
    model: str
    strategy: Callable[[str, str, str], str]


_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

VARIANTS: list[Variant] = [
    Variant("title_only",        _DEFAULT_MODEL, strategy_title),
    Variant("title+desc",        _DEFAULT_MODEL, strategy_title_desc),
    Variant("full (baseline)",   _DEFAULT_MODEL, strategy_full),
    Variant("weighted_title",    _DEFAULT_MODEL, strategy_weighted),
    Variant("full_dedup",        _DEFAULT_MODEL, strategy_full_dedup),
]


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

@dataclass
class CorpusEntry:
    id: int
    title: str
    description: str
    prompt_text: str


def load_corpus() -> list[CorpusEntry]:
    from src.database import SessionLocal
    from src.models.prompt import Prompt

    db = SessionLocal()
    try:
        rows = (
            db.query(Prompt.id, Prompt.title, Prompt.description, Prompt.prompt_text)
            .filter(Prompt.deleted_at.is_(None))
            .all()
        )
    finally:
        db.close()

    return [CorpusEntry(id=r[0], title=r[1], description=r[2], prompt_text=r[3]) for r in rows]


# ---------------------------------------------------------------------------
# Embedder cache: one FastembedEmbedder per model name
# ---------------------------------------------------------------------------

_embedder_cache: dict[str, object] = {}


def get_embedder_for_model(model_name: str):
    if model_name not in _embedder_cache:
        from src.embeddings.fastembed_embedder import FastembedEmbedder
        _embedder_cache[model_name] = FastembedEmbedder(model_name=model_name)
    return _embedder_cache[model_name]


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


# ---------------------------------------------------------------------------
# Per-variant index: list of (corpus_entry, vector)
# ---------------------------------------------------------------------------

@dataclass
class VariantIndex:
    variant: Variant
    entries: list[CorpusEntry]
    matrix: np.ndarray  # shape (N, dim)

    def query(self, query_text: str, top_k: int = 5) -> list[tuple[CorpusEntry, float]]:
        embedder = get_embedder_for_model(self.variant.model)
        q_vec = np.array(embedder.embed_query(query_text), dtype=np.float32)
        sims = self.matrix @ q_vec / (
            np.linalg.norm(self.matrix, axis=1) * np.linalg.norm(q_vec) + 1e-10
        )
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [(self.entries[i], float(sims[i])) for i in top_idx]


def build_index(variant: Variant, corpus: list[CorpusEntry]) -> VariantIndex:
    embedder = get_embedder_for_model(variant.model)
    vecs: list[list[float]] = []
    for entry in corpus:
        source = variant.strategy(entry.title, entry.description, entry.prompt_text)
        vecs.append(embedder.embed_passage(source))
    matrix = np.array(vecs, dtype=np.float32)
    return VariantIndex(variant=variant, entries=corpus, matrix=matrix)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    query: str
    expected_title: str
    found_in_corpus: bool
    rank: int | None  # 1-based; None if expected not found in corpus
    top5: list[tuple[str, float]]  # (title, score)


def score_probe(index: VariantIndex, query: str, expected_title: str) -> ProbeResult:
    # Check corpus membership
    expected_ids = [e.id for e in index.entries if e.title == expected_title]
    if not expected_ids:
        return ProbeResult(
            query=query,
            expected_title=expected_title,
            found_in_corpus=False,
            rank=None,
            top5=[],
        )

    results = index.query(query, top_k=len(index.entries))
    top5 = [(title, score) for (entry, score) in results[:5] for title in [entry.title]]

    rank = None
    for i, (entry, _) in enumerate(results):
        if entry.id in expected_ids:
            rank = i + 1
            break

    return ProbeResult(
        query=query,
        expected_title=expected_title,
        found_in_corpus=True,
        rank=rank,
        top5=top5,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _rank_display(rank: int | None, found: bool) -> str:
    if not found:
        return "NOT IN CORPUS"
    if rank is None:
        return "NOT RANKED"
    return f"#{rank}"


def print_per_query(probe: dict, results: dict[str, ProbeResult]) -> None:
    query = probe["query"]
    expected = probe["expects"]
    print(f"\n{'─' * 60}")
    print(f"  query   : {query}")
    print(f"  expects : {expected}")
    for label, r in results.items():
        print(f"\n  [{label}]  rank={_rank_display(r.rank, r.found_in_corpus)}")
        for i, (title, score) in enumerate(r.top5, 1):
            marker = " ←" if title == expected else ""
            print(f"    {i}. ({score:.4f}) {title}{marker}")


def print_summary(variants: list[Variant], all_probe_results: list[dict[str, ProbeResult]]) -> None:
    labels = [v.label for v in variants]
    n_probes = len(all_probe_results)

    mrr: dict[str, float] = {l: 0.0 for l in labels}
    hits5: dict[str, int] = {l: 0 for l in labels}
    hits1: dict[str, int] = {l: 0 for l in labels}
    evaluated: dict[str, int] = {l: 0 for l in labels}

    for probe_results in all_probe_results:
        for label, r in probe_results.items():
            if not r.found_in_corpus:
                continue
            evaluated[label] += 1
            if r.rank is not None:
                mrr[label] += 1.0 / r.rank
                if r.rank <= 5:
                    hits5[label] += 1
                if r.rank == 1:
                    hits1[label] += 1

    col_w = max(len(l) for l in labels) + 2
    print(f"\n{'═' * 70}")
    print("  SUMMARY")
    print(f"{'═' * 70}")
    header = f"  {'variant':<{col_w}}  {'MRR':>6}  {'hits@1':>7}  {'hits@5':>7}  {'eval':>5}"
    print(header)
    print(f"  {'-' * (col_w + 32)}")
    for label in labels:
        ev = evaluated[label]
        mrr_val = mrr[label] / ev if ev else 0.0
        h1 = f"{hits1[label]}/{ev}"
        h5 = f"{hits5[label]}/{ev}"
        print(f"  {label:<{col_w}}  {mrr_val:>6.3f}  {h1:>7}  {h5:>7}  {ev:>5}")
    print(f"{'═' * 70}")
    print(f"  Total probes: {n_probes}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(probes_path: Path, summary_only: bool) -> int:
    if not probes_path.exists():
        log.error("Probes file not found: %s", probes_path)
        return 1
    probes = yaml.safe_load(probes_path.read_text())
    if not probes:
        log.error("No probes found in %s", probes_path)
        return 1

    log.info("Loading corpus …")
    corpus = load_corpus()
    if not corpus:
        log.error("Corpus is empty — ensure the database is populated")
        return 1
    log.info("Corpus: %d prompts", len(corpus))

    log.info("Building variant indices (%d variants) …", len(VARIANTS))
    indices: list[VariantIndex] = []
    for v in VARIANTS:
        log.info("  building index: %s (model=%s)", v.label, v.model)
        indices.append(build_index(v, corpus))

    all_probe_results: list[dict[str, ProbeResult]] = []

    for probe in probes:
        query = probe["query"]
        expected = probe["expects"]
        probe_results: dict[str, ProbeResult] = {}
        for idx in indices:
            probe_results[idx.variant.label] = score_probe(idx, query, expected)

        all_probe_results.append(probe_results)

        if not summary_only:
            print_per_query(probe, probe_results)

    print_summary(VARIANTS, all_probe_results)
    return 0


def main() -> None:
    default_probes = Path(__file__).parent / "eval_probes.yaml"
    parser = argparse.ArgumentParser(description="Evaluate embedding retrieval quality")
    parser.add_argument(
        "--probes",
        type=Path,
        default=default_probes,
        metavar="PATH",
        help=f"Path to probe YAML file (default: {default_probes})",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only the aggregate summary table, suppress per-query detail",
    )
    args = parser.parse_args()

    sys.exit(run(probes_path=args.probes, summary_only=args.summary_only))


if __name__ == "__main__":
    main()
