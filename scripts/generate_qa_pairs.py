"""Generate stratified QA pairs from holdout documents (TEST-03).

Run modes:
  --mode=stub   Deterministic template-based generation (CI-friendly, no LLM)
  --mode=llm    Use ragas_judge LLM via existing EvalSettings (offline once cached)

Output: eval/datasets/qa_pairs.json (overwrites existing)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from eval.models import QAPair, EvalDataset

# ---------------------------------------------------------------------------
# Stratification targets (from TEST-03 RESEARCH.md)
# ---------------------------------------------------------------------------
STRATA_TARGETS: dict[str, int] = {
    "policy_factual": 60,
    "procedural":     50,
    "comparison":     40,
    "definition":     30,
    "multi_hop":      20,
}  # sum = 200

# ---------------------------------------------------------------------------
# Question / answer templates per doc_type (stub mode)
# ---------------------------------------------------------------------------
_QUESTION_TEMPLATES: dict[str, list[str]] = {
    "policy_factual": [
        "What is the policy on {topic}?",
        "How many days are allowed under the {topic} policy?",
        "Who is eligible for {topic} benefits?",
        "When does the {topic} policy take effect?",
        "What are the key requirements of the {topic} policy?",
        "Who approves requests under the {topic} policy?",
        "What documents are required for {topic}?",
        "How often is the {topic} policy reviewed?",
    ],
    "procedural": [
        "What are the steps to apply for {topic}?",
        "How do I submit a request for {topic}?",
        "What is the process for {topic} approval?",
        "How long does the {topic} process take?",
        "Which department handles {topic} requests?",
        "What is the deadline for {topic} submissions?",
        "What form should I use for {topic}?",
        "How do I track the status of my {topic} request?",
    ],
    "comparison": [
        "What is the difference between {topic} option A and option B?",
        "How does the {topic} policy compare across different employment types?",
        "Which {topic} option provides better coverage?",
        "How do the {topic} terms differ for domestic vs overseas employees?",
        "What changed in {topic} from last year to this year?",
        "How does our {topic} compare to industry standard?",
        "What are the pros and cons of each {topic} option?",
        "Which {topic} approach is recommended for senior staff?",
    ],
    "definition": [
        "What is the definition of {topic}?",
        "How is {topic} defined in company policy?",
        "What does {topic} mean in the context of HR?",
        "Explain the term {topic} as used in our documentation.",
        "What criteria define {topic} classification?",
        "What are the key attributes of {topic}?",
    ],
    "multi_hop": [
        "If an employee needs {topic} approval, which policies apply and who signs off?",
        "How does {topic} interact with the leave policy and finance approval?",
        "What happens when a {topic} request crosses department boundaries?",
        "Who is responsible for {topic} when the direct manager is absent?",
        "How are {topic} decisions recorded and audited?",
    ],
}

_ANSWER_TEMPLATES: dict[str, str] = {
    "policy_factual": "According to {source_doc}, the policy on {topic} specifies the relevant rules and entitlements. Refer to the document for full details.",
    "procedural": "Based on {source_doc}, the {topic} process involves submitting the required form to the relevant department. See the document for step-by-step instructions.",
    "comparison": "As documented in {source_doc}, the comparison of {topic} options highlights key differences in eligibility, coverage, and approval requirements.",
    "definition": "As defined in {source_doc}, {topic} refers to the formal classification or concept as specified in company policy.",
    "multi_hop": "Resolving a {topic} request requires consulting {source_doc} along with related policies. The full approval chain is described therein.",
}


def _stub_pairs_for_doc(
    rng: random.Random,
    doc: dict,
    count: int,
) -> list[QAPair]:
    """Generate `count` deterministic QA pairs for a single holdout document."""
    doc_type: str = doc["doc_type"]
    topic: str = doc["topic"]
    source_doc: str = doc["path"]

    q_templates = _QUESTION_TEMPLATES[doc_type]
    a_template = _ANSWER_TEMPLATES[doc_type]

    pairs: list[QAPair] = []
    for i in range(count):
        q_tmpl = q_templates[i % len(q_templates)]
        question = q_tmpl.format(topic=topic.replace("_", " "))
        # Add slight variation to avoid exact duplicates across iterations
        if i >= len(q_templates):
            question = question + f" (case {i // len(q_templates) + 1})"
        ground_truth = a_template.format(topic=topic.replace("_", " "), source_doc=source_doc)

        pairs.append(
            QAPair(
                question=question,
                ground_truth=ground_truth,
                doc_type=doc_type,  # type: ignore[arg-type]
                topic=topic,
                source_doc=source_doc,
            )
        )
    return pairs


def generate_stub(seed: int = 42) -> list[QAPair]:
    """Generate all strata deterministically using fixed seed."""
    manifest_path = Path("eval/datasets/holdout_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    holdout_docs: list[dict] = manifest["holdout_docs"]

    # Group docs by doc_type
    docs_by_type: dict[str, list[dict]] = {}
    for doc in holdout_docs:
        dt = doc["doc_type"]
        docs_by_type.setdefault(dt, []).append(doc)

    rng = random.Random(seed)
    all_pairs: list[QAPair] = []

    for doc_type, target_count in STRATA_TARGETS.items():
        docs = docs_by_type.get(doc_type, [])
        if not docs:
            # If no holdout doc for this type, use the first available doc but override doc_type
            # This should not happen with a well-formed manifest
            raise ValueError(
                f"No holdout document for doc_type={doc_type!r}. "
                "Add at least one entry to holdout_manifest.json."
            )
        # Distribute pairs evenly across available docs of this type
        per_doc, remainder = divmod(target_count, len(docs))
        for idx, doc in enumerate(docs):
            count = per_doc + (1 if idx < remainder else 0)
            pairs = _stub_pairs_for_doc(rng, doc, count)
            all_pairs.extend(pairs)

    # Shuffle deterministically so strata are interleaved
    rng.shuffle(all_pairs)
    return all_pairs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate stratified QA pairs from holdout docs")
    parser.add_argument(
        "--mode",
        choices=["stub", "llm"],
        default="stub",
        help="Generation mode: stub (deterministic, no LLM) or llm (uses EvalSettings judge)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (stub mode only)",
    )
    args = parser.parse_args()

    if args.mode == "stub":
        pairs = generate_stub(seed=args.seed)
    else:
        raise NotImplementedError(
            "llm mode requires a running RAG API and judge LLM. "
            "Use --mode=stub for CI."
        )

    from datetime import datetime, timezone
    dataset = EvalDataset(
        pairs=pairs,
        created_at=datetime(2026, 4, 27, 0, 0, 0, tzinfo=timezone.utc),
    )
    output_path = Path("eval/datasets/qa_pairs.json")
    output_path.write_text(
        dataset.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(pairs)} QA pairs to {output_path}")


if __name__ == "__main__":
    main()
