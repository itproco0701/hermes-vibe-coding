#!/usr/bin/env python3
"""strata-plan — StraTA-style plan sampling + self-judgment for any agent.

Self-contained (Python 3.10+, stdlib only). No network calls. Generates
candidate plan cards, lets the user pick one, and judges plan vs outcome
alignment with a deterministic fallback scorer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(os.getenv("STRATA_PLAN_ROOT", "."))
PLANS_DIR = ROOT / ".strata-plans"
DEFAULT_N = 3

STRATEGY_TEMPLATES: list[dict[str, str]] = [
    {
        "tag": "minimal",
        "one_liner": "Touch the fewest files and add the least new code; reuse what's there.",
        "tradeoff": "Fast and safe, but may force a slightly awkward fit if existing abstractions don't quite line up.",
        "risk": "low",
    },
    {
        "tag": "structured",
        "one_liner": "Add a thin layer (helper / middleware / new module) to keep changes isolated.",
        "tradeoff": "Clean separation, easier to test; costs a small amount of new surface area.",
        "risk": "medium",
    },
    {
        "tag": "rewrite",
        "one_liner": "Refactor the affected area to make the change natural instead of fighting it.",
        "tradeoff": "Better long-term shape; risks scope creep and longer review cycle.",
        "risk": "high",
    },
]


@dataclass
class PlanCard:
    tag: str
    one_liner: str
    tradeoff: str
    risk: str
    steps: list[str] = field(default_factory=list)


@dataclass
class Bundle:
    intent: str
    created_at: str
    cards: list[PlanCard]


@dataclass
class Judgment:
    score: float
    reason: str
    missed_steps: list[str] = field(default_factory=list)
    next_action: str = ""


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _ensure_plans_dir() -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)


def _infer_steps(intent: str) -> list[str]:
    """Lightweight step inference. In real use the LLM fills this in.
    Here we extract imperative-looking verbs so the artifact is non-empty
    and the judge has something to score against.
    """
    verbs = ("add", "create", "modify", "update", "refactor", "fix", "remove", "wire", "wire-up", "expose", "test")
    tokens = re.findall(r"\b\w+\b", intent.lower())
    steps: list[str] = []
    for tok in tokens:
        if tok in verbs and len(steps) < 6:
            steps.append(f"{tok} (derived from intent)")
    if not steps:
        steps = ["explore relevant code", "draft change", "verify"]
    return steps


def _build_cards(intent: str, n: int) -> list[PlanCard]:
    templates = (STRATEGY_TEMPLATES * ((n // len(STRATEGY_TEMPLATES)) + 1))[:n]
    cards: list[PlanCard] = []
    for t in templates:
        cards.append(PlanCard(
            tag=t["tag"],
            one_liner=t["one_liner"],
            tradeoff=t["tradeoff"],
            risk=t["risk"],
            steps=_infer_steps(intent),
        ))
    return cards


def cmd_sample(intent: str, n: int) -> int:
    if n < 1 or n > 6:
        print("n must be 1-6", file=sys.stderr)
        return 2
    cards = _build_cards(intent, n)
    bundle = Bundle(intent=intent, created_at=_ts(), cards=cards)
    _ensure_plans_dir()
    out = PLANS_DIR / f"bundle-{_ts()}.json"
    out.write_text(json.dumps(asdict(bundle), ensure_ascii=False, indent=2))
    print(f"== Sampled {n} plan strategies for: {intent}")
    print(f"bundle: {out}")
    print()
    for i, c in enumerate(cards, 1):
        print(f"  [{i}] {c.tag:<10}  {c.one_liner}")
    print()
    print(f"Next: strata-plan pick {out.name}    (or `strata-plan pick` to use latest)")
    return 0


def _load_bundle(bundle_arg: str | None) -> Path:
    if bundle_arg:
        p = PLANS_DIR / bundle_arg
        if not p.exists():
            sys.exit(f"bundle not found: {p}")
        return p
    bundles = sorted(PLANS_DIR.glob("bundle-*.json"))
    if not bundles:
        sys.exit("no sample bundles in .strata-plans/ — run `strata-plan sample <intent>` first")
    return bundles[-1]


def cmd_pick(bundle_arg: str | None) -> int:
    bp = _load_bundle(bundle_arg)
    raw = json.loads(bp.read_text()); raw["cards"] = [PlanCard(**c) for c in raw["cards"]]; bundle = Bundle(**raw)
    print(f"== Bundle: {bp.name}")
    print(f"intent: {bundle.intent}")
    print(f"created: {bundle.created_at}")
    print()
    for i, c in enumerate(bundle.cards, 1):
        print(f"  [{i}] {c.tag}  {c.one_liner}")
    print()
    choice = input("Pick 1/2/3 (or 'q' to abort): ").strip()
    if choice.lower() == "q":
        return 0
    if not choice.isdigit():
        sys.exit("invalid input")
    idx = int(choice) - 1
    if not (0 <= idx < len(bundle.cards)):
        sys.exit("out of range")
    picked = bundle.cards[idx]
    plan_path = PLANS_DIR / f"plan-{_ts()}-{picked.tag}.md"
    plan_path.write_text(_render_plan_md(bundle.intent, picked))
    print(f"Plan saved: {plan_path}")
    return 0


def _render_plan_md(intent: str, card: PlanCard) -> str:
    steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(card.steps)) or "1. (fill in)"
    return textwrap.dedent(f"""\
        # Plan: {intent}

        ## Strategy
        `{card.tag}` — {card.one_liner}

        ## Tradeoff
        {card.tradeoff}

        ## Risk
        {card.risk}

        ## Implementation steps
        {steps}

        ## Files to modify
        <!-- LLM: fill in after exploring the repo -->

        ## Files NOT to touch
        <!-- LLM: list explicitly so the executor doesn't drift -->

        ## Definition of done
        - [ ] <!-- LLM: testable criteria -->

        ## Rollback
        <!-- LLM: how to undo cleanly -->
        """)


def _judge(plan: str, outcome: str, score_hint: str | None) -> Judgment:
    steps = re.findall(r"^\s*\d+\.\s+(.+?)$", plan, flags=re.MULTILINE)
    if not steps:
        return Judgment(
            score=0.5,
            reason="plan had no numbered steps — nothing to verify",
            next_action="add atomic steps to plan",
        )
    addressed = 0
    missed: list[str] = []
    out_lower = outcome.lower()
    for s in steps:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", " ", s.lower()).strip()[:40]
        tokens = [t for t in key.split() if len(t) > 3]
        if key and any(tok in out_lower for tok in tokens):
            addressed += 1
        else:
            missed.append(s.strip())
    score = round(addressed / max(1, len(steps)), 2)
    if score_hint:
        try:
            score = round(0.5 * score + 0.5 * float(score_hint), 2)
        except ValueError:
            pass
    if score < 0.6:
        nxt = "revise plan to cover missed steps, re-execute"
    elif score < 0.86:
        nxt = "log the gap, continue; address in next iteration"
    else:
        nxt = "commit; record plan↔outcome pair as 'good pattern' in mistake journal"
    return Judgment(
        score=score,
        reason=f"addressed {addressed}/{len(steps)} numbered steps",
        missed_steps=missed,
        next_action=nxt,
    )


def cmd_judge(plan: str, outcome: str, score_hint: str | None) -> int:
    if not Path(plan).exists():
        sys.exit(f"plan not found: {plan}")
    plan_text = Path(plan).read_text()
    j = _judge(plan_text, outcome, score_hint)
    _ensure_plans_dir()
    log = PLANS_DIR / "judgments.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "plan": plan,
            "score": j.score,
            "reason": j.reason,
            "next_action": j.next_action,
            "missed": j.missed_steps,
            "timestamp": _ts(),
        }, ensure_ascii=False) + "\n")
    print(json.dumps(asdict(j), indent=2, ensure_ascii=False))
    print(f"\nLogged to {log}")
    if j.score < 0.6:
        _bridge_to_mistake_journal(plan, j)
        print("Score < 0.6 — written to .vibe-mistakes.json as a lesson.")
    else:
        print("Score ≥ 0.6 — no mistake journal entry needed.")
    return 0


def _bridge_to_mistake_journal(plan_path: str, j) -> None:
    """
    Write missed_steps into the vibe-coding Mistake Journal (\.vibe-mistakes\.json)
    so future loops in the same project auto-warn about this gap.
    Uses the canonical key shape: category=plan_mismatch, context=intent, mistake=missed step, lesson=next_action.
    """
    journal_path = Path(".vibe-mistakes.json")
    if journal_path.exists():
        journal = json.loads(journal_path.read_text() or '{"project":"","created_at":"","mistakes":[]}')
    else:
        journal = {"project": Path.cwd().name, "created_at": datetime.now().isoformat(), "mistakes": []}
    mistakes = journal.setdefault("mistakes", [])
    for step in (j.missed_steps or []):
        key = (plan_path, step)
        existing = next((m for m in mistakes if (m.get("context"), m.get("mistake")) == key), None)
        if existing:
            existing["occurrence_count"] = existing.get("occurrence_count", 1) + 1
            existing["last_occurred"] = datetime.now().isoformat()
        else:
            mistakes.append({
                "id": hashlib.md5(f"plan_mismatch:{plan_path}:{step}:{datetime.now()}".encode()).hexdigest()[:12],
                "category": "plan_mismatch",
                "context": plan_path,
                "mistake": f"plan listed step but execution skipped it: {step}",
                "lesson": j.next_action or "revise plan to cover missed steps, re-execute",
                "related_files": [],
                "timestamp": datetime.now().isoformat(),
                "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "occurrence_count": 1,
                "last_occurred": datetime.now().isoformat(),
            })
    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False))


def cmd_bundle(intent: str) -> int:
    if cmd_sample(intent, DEFAULT_N) != 0:
        return 1
    return cmd_pick(None)


def cmd_status() -> int:
    bundles = sorted(PLANS_DIR.glob("bundle-*.json"))
    plans = sorted(PLANS_DIR.glob("plan-*.md"))
    judgments = sorted(PLANS_DIR.glob("judgments.jsonl"))
    print(f"bundles: {len(bundles)}   plans: {len(plans)}   judgments: {len(judgments)}")
    if judgments:
        last = judgments[-1]
        lines = last.read_text().strip().splitlines()
        if lines:
            last_j = json.loads(lines[-1])
            print(f"last judgment: score={last_j['score']}  next={last_j['next_action']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="strata-plan", description=textwrap.dedent(__doc__ or "").strip())
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("sample", help="generate N candidate plan cards")
    sp.add_argument("intent")
    sp.add_argument("-n", type=int, default=DEFAULT_N)
    sp.set_defaults(func=lambda a: cmd_sample(a.intent, a.n))
    sp = sub.add_parser("pick", help="interactively pick one from a bundle (default: latest)")
    sp.add_argument("bundle", nargs="?", default=None)
    sp.set_defaults(func=lambda a: cmd_pick(Path(a.bundle).name if a.bundle else None))
    sp = sub.add_parser("judge", help="judge plan↔outcome alignment")
    sp.add_argument("plan")
    sp.add_argument("outcome")
    sp.add_argument("--score-hint", default=None)
    sp.set_defaults(func=lambda a: cmd_judge(a.plan, a.outcome, a.score_hint))
    sp = sub.add_parser("bundle", help="sample + pick in one call")
    sp.add_argument("intent")
    sp.set_defaults(func=lambda a: cmd_bundle(a.intent))
    sub.add_parser("status", help="show counts + last judgment").set_defaults(func=lambda a: cmd_status())
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    return 0 if rc is None else rc


if __name__ == "__main__":
    sys.exit(main())
