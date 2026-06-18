#!/usr/bin/env python3
"""strata-plan — StraTA-style plan sampling + self-judgment for any agent.

Self-contained (Python 3.10+, stdlib only). No LLM call required for sampling —
cards are sampled from a built-in template library with optional domain-specific
overrides (db-migration, api-design, perf, test-fix).

Usage:
    strata-plan sample "<intent>"            # generate N candidate plan cards
    strata-plan sample "<intent>" -t db-migration   # use a domain template
    strata-plan pick [bundle.json]           # interactively pick a winner
    strata-plan judge <plan.md> <outcome.md> # score a plan↔outcome pair
    strata-plan judge <plan.md> --outcome "..."   # inline outcome text
    strata-plan status                       # show counts + last judgment
    strata-plan report                       # health summary across judgments
    strata-plan bundle "<intent>"            # sample + pick in one call
    strata-plan rollback                     # remove last judgment
    strata-plan templates                    # list available templates
    strata-plan rollout-sim                  # CPU mock of hierarchical rollout

The script always exits 0 on success. Non-zero on usage errors so vibe_loop.py
can detect and route fallbacks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import textwrap
import importlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

PLANS_DIR = Path(".strata-plans")
JUDGMENTS_FILE = PLANS_DIR / "judgments.jsonl"
DEFAULT_N = 3

SCORE_THRESHOLDS: dict[str, float] = {
    "refactor":    0.65,
    "rewrite":     0.55,
    "fix":         0.45,
    "debug":       0.45,
    "api":         0.7,
    "db":          0.75,
    "migration":   0.8,
    "perf":        0.6,
    "test":        0.6,
    "docs":        0.5,
    "default":     0.6,
}

INTENT_KEYWORDS: dict[str, list[str]] = {
    "db":          ["migration", "schema", "database", "postgres", "mysql", "sqlalchemy", "alembic", "migrate"],
    "api":         ["endpoint", "rest", "graphql", "api", "route", "controller", "fastapi", "flask"],
    "perf":        ["slow", "n+1", "performance", "optimi", "latency", "throughput", "cache"],
    "test":        ["test", "pytest", "jest", "coverage", "tdd"],
    "fix":         ["fix", "bug", "broken", "fails", "error", "修復", "修bug", "404", "500", "422"],
    "debug":       ["debug", "trace", "排查", "stack trace"],
    "refactor":    ["refactor", "cleanup", "rename", "重構"],
    "rewrite":     ["rewrite", "rearchitect", "重寫", "rebuild"],
    "migration":   ["migrate", "upgrade", "遷移", "搬"],
    "docs":        ["docs", "readme", "documentation", "文件"],
}


STRATEGY_TEMPLATES: list[dict[str, str]] = [
    {
        "tag": "minimal",
        "one_liner": "Touch the fewest files and add the least new code; reuse what's there.",
        "tradeoff": "Fast and safe, but may force a slightly awkward fit if existing abstractions don't quite line up.",
        "risk": "low",
        "best_for": "fix, debug, docs",
    },
    {
        "tag": "structured",
        "one_liner": "Add a thin layer (helper / middleware / new module) to keep changes isolated.",
        "tradeoff": "Clean separation, easier to test; costs a small amount of new surface area.",
        "risk": "medium",
        "best_for": "api, perf, test",
    },
    {
        "tag": "rewrite",
        "one_liner": "Refactor the affected area to make the change natural instead of fighting it.",
        "tradeoff": "Better long-term shape; risks scope creep and longer review cycle.",
        "risk": "high",
        "best_for": "refactor, rewrite, migration",
    },
    {
        "tag": "transactional",
        "one_liner": "Wrap DB migration in a transaction with rollback script; back up before applying.",
        "tradeoff": "Safest for production data; can be slow on large tables and requires downtime window.",
        "risk": "medium",
        "best_for": "db, migration",
    },
    {
        "tag": "contract-first",
        "one_liner": "Define the request/response schema (Pydantic / TypeScript type) first, then implement.",
        "tradeoff": "Catches contract mismatches early; needs discipline to keep schemas in sync with code.",
        "risk": "medium",
        "best_for": "api",
    },
    {
        "tag": "benchmark-first",
        "one_liner": "Write a measurement script before changing code; assert perf improves, never regress.",
        "tradeoff": "Adds setup cost; pays off when chasing subtle perf regressions.",
        "risk": "low",
        "best_for": "perf",
    },
]


@dataclass
class PlanCard:
    tag: str
    one_liner: str
    tradeoff: str
    risk: str
    steps: list[str] = field(default_factory=list)
    best_for: str = ""


@dataclass
class Bundle:
    intent: str
    created_at: str
    cards: list[PlanCard]
    template: str = "default"


@dataclass
class Judgment:
    score: float
    reason: str
    missed_steps: list[str] = field(default_factory=list)
    next_action: str = ""
    threshold: float = 0.6
    intent_category: str = "default"
    steps_total: int = 0
    steps_addressed: int = 0


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_plans_dir() -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)


def _detect_intent_category(intent: str) -> str:
    intent_l = intent.lower()
    best, best_score = "default", 0
    for cat, kws in INTENT_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in intent_l)
        if score > best_score:
            best, best_score = cat, score
    return best


def _resolve_template(template: str | None, intent: str) -> list[dict[str, Any]]:
    if template and template != "default":
        try:
            mod = importlib.import_module(f"strata_templates.{template}")
            cards = mod.build(intent)
            return [{"tag": c.tag, "one_liner": c.one_liner, "tradeoff": c.tradeoff,
                     "risk": c.risk, "best_for": getattr(c, "best_for", "")} for c in cards]
        except ModuleNotFoundError:
            print(f"⚠️ template '{template}' not found, falling back to default",
                  file=sys.stderr)
    category = _detect_intent_category(intent)
    selected: list[dict[str, Any]] = []
    selected.append(STRATEGY_TEMPLATES[0])
    for t in STRATEGY_TEMPLATES[1:]:
        if category in (t.get("best_for") or ""):
            selected.append(t)
    if len(selected) < 3:
        for t in STRATEGY_TEMPLATES:
            if t not in selected:
                selected.append(t)
                if len(selected) >= 3:
                    break
    return selected


def _seed_steps_for(tag: str, intent: str) -> list[str]:
    i = intent[:60]
    by_tag: dict[str, list[str]] = {
        "minimal": [
            f"Locate the smallest surface that satisfies: {i}",
            f"Edit in place; preserve existing types and naming",
            f"Run targeted test for the touched module",
            f"Verify no other module references the changed symbol",
        ],
        "structured": [
            f"Define the helper / middleware / new module boundary for: {i}",
            f"Keep the new layer thin and free of business logic",
            f"Wire it into the existing call site with one adapter line",
            f"Add a unit test for the new layer",
        ],
        "rewrite": [
            f"Sketch the desired final shape of the affected area for: {i}",
            f"Migrate callers in small commits, not one big-bang refactor",
            f"Keep behaviour identical at every commit boundary",
            f"Update tests and docs after each commit",
        ],
        "transactional": [
            f"Back up the affected tables / DB before touching anything",
            f"Write forward + rollback SQL scripts in a single transaction",
            f"Run migration on a staging copy; measure lock duration",
            f"Apply on production during low-traffic window; verify with smoke test",
        ],
        "contract-first": [
            f"Define the request/response schema for: {i}",
            f"Generate server stub from the schema",
            f"Wire stub into the router; add validation tests",
            f"Implement handler behind the validated contract",
        ],
        "benchmark-first": [
            f"Write a reproducer that times the slow path for: {i}",
            f"Establish baseline numbers; commit them to the test suite",
            f"Apply the suspected optimisation",
            f"Re-run benchmark; assert no regression in any existing metric",
        ],
    }
    return by_tag.get(tag, by_tag["minimal"])


def cmd_sample(intent: str, n: int, template: str | None) -> int:
    if n < 1:
        print("n must be >= 1", file=sys.stderr); return 2
    _ensure_plans_dir()
    pool = _resolve_template(template, intent)
    pool = (pool * ((n // len(pool)) + 1))[:n]
    cards: list[PlanCard] = []
    for raw in pool:
        cards.append(PlanCard(
            tag=raw["tag"],
            one_liner=raw["one_liner"],
            tradeoff=raw["tradeoff"],
            risk=raw["risk"],
            steps=_seed_steps_for(raw["tag"], intent),
            best_for=raw.get("best_for", ""),
        ))
    bundle = Bundle(
        intent=intent,
        created_at=_now_iso(),
        cards=cards,
        template=template or "auto",
    )
    bp = PLANS_DIR / f"bundle-{_ts()}.json"
    bp.write_text(json.dumps(asdict(bundle), ensure_ascii=False, indent=2))
    print(f"== Sampled {n} plan strategies for: {intent}")
    print(f"intent_category: {_detect_intent_category(intent)}")
    print(f"template: {bundle.template}")
    print(f"bundle: {bp.name}")
    for i, c in enumerate(cards, 1):
        print(f"  [{i}] {c.tag:<10} risk={c.risk:<6}  {c.one_liner[:70]}")
    return 0


def _load_bundle(bundle_arg: str | None) -> Path:
    if bundle_arg:
        p = Path(bundle_arg)
        if p.is_dir():
            p = p / ".strata-plans"
        if p.name.startswith("bundle-") or p.suffix == ".json":
            cand = p if p.is_absolute() else PLANS_DIR / p.name
            if cand.exists():
                return cand
        if not p.exists():
            p2 = PLANS_DIR / bundle_arg
            if p2.exists():
                return p2
        sys.exit(f"bundle not found: {bundle_arg}")
    bundles = sorted(PLANS_DIR.glob("bundle-*.json"))
    if not bundles:
        sys.exit("no sample bundles in .strata-plans/ — run `strata-plan sample <intent>` first")
    return bundles[-1]


def _load_bundle_obj(bp: Path) -> Bundle:
    raw = json.loads(bp.read_text())
    cards_raw = raw.get("cards", [])
    cards = [
        PlanCard(
            tag=c.get("tag", "?"),
            one_liner=c.get("one_liner", ""),
            tradeoff=c.get("tradeoff", ""),
            risk=c.get("risk", "?"),
            steps=c.get("steps", []),
            best_for=c.get("best_for", ""),
        )
        for c in cards_raw
    ]
    return Bundle(
        intent=raw.get("intent", ""),
        created_at=raw.get("created_at", ""),
        cards=cards,
        template=raw.get("template", "default"),
    )


def cmd_pick(bundle_arg: str | None) -> int:
    bp = _load_bundle(bundle_arg)
    bundle = _load_bundle_obj(bp)
    print(f"== Bundle: {bp.name}")
    print(f"intent: {bundle.intent}")
    print(f"created: {bundle.created_at}")
    print(f"template: {bundle.template}")
    print()
    for i, c in enumerate(bundle.cards, 1):
        print(f"  [{i}] {c.tag:<10}  {c.one_liner}")
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


NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.+?)$", re.MULTILINE)
BULLET_RE   = re.compile(r"^\s*[-*]\s+(.+?)$", re.MULTILINE)
CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.+?)$", re.MULTILINE)
HEADING_RE  = re.compile(r"^##\s+Implementation steps\s*\n(.*?)(?=\n##|\Z)", re.DOTALL | re.IGNORECASE)


def _extract_steps(plan: str) -> list[str]:
    section = HEADING_RE.search(plan)
    if section:
        body = section.group(1)
    else:
        body = plan
    steps = NUMBERED_RE.findall(body)
    if not steps:
        steps = CHECKBOX_RE.findall(body)
    if not steps:
        steps = BULLET_RE.findall(body)
    if not steps:
        numbered = NUMBERED_RE.findall(plan)
        if numbered:
            steps = numbered
    if not steps:
        sentences = re.findall(r"(?:^|\n)\s*([A-Z][^.\n]{15,140}\.)", plan)
        steps = sentences[:10]
    return [s.strip() for s in steps if s.strip()]


def _judge(plan: str, outcome: str, score_hint: str | None,
           intent: str = "", threshold: float | None = None) -> Judgment:
    steps = _extract_steps(plan)
    category = _detect_intent_category(intent) if intent else "default"
    eff_threshold = threshold if threshold is not None else SCORE_THRESHOLDS.get(category, 0.6)
    if not steps:
        return Judgment(
            score=0.5,
            reason="plan had no parseable steps — nothing to verify",
            next_action="add atomic steps to plan",
            threshold=eff_threshold,
            intent_category=category,
        )
    out_lower = outcome.lower()
    addressed = 0
    missed: list[str] = []
    for s in steps:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", " ", s.lower()).strip()[:60]
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
    if score < eff_threshold:
        nxt = "revise plan to cover missed steps, re-execute"
    elif score < 0.86:
        nxt = "log the gap, continue; address in next iteration"
    else:
        nxt = "commit; record plan↔outcome pair as 'good pattern' in mistake journal"
    return Judgment(
        score=score,
        reason=f"addressed {addressed}/{len(steps)} parseable steps (category={category}, threshold={eff_threshold})",
        missed_steps=missed,
        next_action=nxt,
        threshold=eff_threshold,
        intent_category=category,
        steps_total=len(steps),
        steps_addressed=addressed,
    )


def cmd_judge(plan: str, outcome_arg: str | None, score_hint: str | None,
              threshold: float | None) -> int:
    plan_path = Path(plan)
    if not plan_path.exists():
        sys.exit(f"plan not found: {plan}")
    plan_text = plan_path.read_text()
    if outcome_arg and Path(outcome_arg).exists():
        outcome_text = Path(outcome_arg).read_text()
    elif outcome_arg:
        outcome_text = outcome_arg
    else:
        sys.exit("must supply outcome as path or inline text")
    intent_match = re.search(r"^#\s*Plan:\s*(.+)$", plan_text, flags=re.MULTILINE)
    intent = intent_match.group(1).strip() if intent_match else ""
    j = _judge(plan_text, outcome_text, score_hint, intent=intent, threshold=threshold)
    _ensure_plans_dir()
    log_entry = {
        "plan": str(plan_path),
        "score": j.score,
        "reason": j.reason,
        "next_action": j.next_action,
        "missed": j.missed_steps,
        "intent": intent,
        "intent_category": j.intent_category,
        "threshold": j.threshold,
        "steps_total": j.steps_total,
        "steps_addressed": j.steps_addressed,
        "timestamp": _now_iso(),
    }
    with JUDGMENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    print(json.dumps(asdict(j), indent=2, ensure_ascii=False))
    print(f"\nLogged to {JUDGMENTS_FILE}")
    project_path = Path.cwd()
    if j.score < j.threshold:
        print(f"Score {j.score} < threshold {j.threshold} — bridge to Mistake Journal will fire.")
        bridge_ok = _bridge_to_mistake_journal(project_path, j, str(plan_path), intent)
        if bridge_ok:
            print("→ written to .vibe-mistakes.json (category=missed_steps).")
        else:
            print("(skip: bridge errored or no missed steps to record)")
    else:
        print("Score >= threshold — no Mistake Journal entry needed.")
    return 0


def _bridge_to_mistake_journal(project_path: Path, j: Judgment, plan_path: str, intent: str) -> bool:
    """If the score is below the category threshold, append an entry to .vibe-mistakes.json.

    The bridge is opt-out friendly: any error is swallowed and logged so vibe-coding's
    primary loop is never blocked by a journal write failure.
    """
    if not j.missed_steps:
        return False
    return _append_mistake_journal(project_path, j, plan_path, intent)



def _append_mistake_journal(project_path: Path, j: Judgment, plan_path: str, intent: str) -> bool:
    """Append a single mistake entry to .vibe-mistakes.json in project_path.

    Mirrors the schema used by vibe-coding/scripts/vibe_loop.py so both sides
    see the same file. Returns True on success, False on any error so the
    primary judge loop is never blocked.
    """
    try:
        import hashlib
        from datetime import datetime as _dt
        mf = project_path / ".vibe-mistakes.json"
        if mf.exists():
            journal = json.loads(mf.read_text())
        else:
            journal = {"project": project_path.name, "created_at": _dt.now().isoformat(), "mistakes": []}
        category = f"strata_missed_{j.intent_category}"
        lesson = f"Plan {Path(plan_path).name} missed steps: {', '.join(j.missed_steps[:3])}"
        # de-dupe: same category + first 50 chars of lesson
        sig = (category, lesson[:50])
        for m in journal.get("mistakes", []):
            if (m.get("category"), (m.get("lesson", "")[:50])) == sig:
                m["occurrence_count"] = m.get("occurrence_count", 1) + 1
                m["last_occurred"] = _dt.now().isoformat()
                break
        else:
            journal.setdefault("mistakes", []).append({
                "id": hashlib.md5(f"{category}:{lesson}:{_dt.now()}".encode()).hexdigest()[:12],
                "category": category,
                "context": f"intent: {intent}",
                "mistake": f"score={j.score} threshold={j.threshold} missed={len(j.missed_steps)}",
                "lesson": lesson,
                "related_files": [plan_path],
                "timestamp": _dt.now().isoformat(),
                "session_id": _dt.now().strftime("%Y%m%d_%H%M%S"),
                "occurrence_count": 1,
                "last_occurred": _dt.now().isoformat(),
                "source": "strata-plan",
            })
        mf.write_text(json.dumps(journal, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        print(f"  ⚠️  journal bridge failed: {e}", file=sys.stderr)
        return False


def cmd_bundle(intent: str, template: str | None) -> int:
    if cmd_sample(intent, DEFAULT_N, template) != 0:
        return 1
    return cmd_pick(None)


def cmd_status() -> int:
    bundles = sorted(PLANS_DIR.glob("bundle-*.json"))
    plans = sorted(PLANS_DIR.glob("plan-*.md"))
    print(f"bundles: {len(bundles)}   plans: {len(plans)}   judgments: ", end="")
    if JUDGMENTS_FILE.exists():
        n = sum(1 for _ in JUDGMENTS_FILE.open())
        print(n)
        lines = JUDGMENTS_FILE.read_text().strip().splitlines()
        if lines:
            last = json.loads(lines[-1])
            print(f"last judgment: score={last['score']}  category={last.get('intent_category','?')}  "
                  f"threshold={last.get('threshold','?')}  next={last['next_action']}")
    else:
        print("0")
    return 0


def cmd_report(last: int) -> int:
    if not JUDGMENTS_FILE.exists():
        print("no judgments yet — run `strata-plan judge` first")
        return 0
    lines = JUDGMENTS_FILE.read_text().strip().splitlines()
    if not lines:
        print("judgments file is empty")
        return 0
    rows = [json.loads(l) for l in lines]
    rows = rows[-last:] if last > 0 else rows
    by_cat: dict[str, list[float]] = {}
    below = 0
    for r in rows:
        cat = r.get("intent_category", "default")
        by_cat.setdefault(cat, []).append(r["score"])
        if r["score"] < r.get("threshold", 0.6):
            below += 1
    print(f"== StrATA Plan Report — {len(rows)} judgments (last {last or 'all'})")
    print(f"below threshold: {below}/{len(rows)}  ({below/max(1,len(rows))*100:.0f}%)")
    print()
    print(f"{'category':<12} {'count':>5} {'avg':>6} {'min':>6} {'max':>6}")
    for cat, scores in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"{cat:<12} {len(scores):>5} {sum(scores)/len(scores):>6.2f} "
              f"{min(scores):>6.2f} {max(scores):>6.2f}")
    missed_pool: list[str] = []
    for r in rows:
        if r["score"] < r.get("threshold", 0.6):
            missed_pool.extend(r.get("missed", []))
    if missed_pool:
        print()
        print(f"Most-frequently-missed step patterns (out of {len(missed_pool)} missed steps):")
        from collections import Counter
        toks = Counter()
        for m in missed_pool:
            for tok in re.findall(r"[a-z\u4e00-\u9fff]{4,}", m.lower()):
                toks[tok] += 1
        for tok, n in toks.most_common(8):
            print(f"  {n}x  {tok}")
    return 0


def cmd_rollback() -> int:
    if not JUDGMENTS_FILE.exists():
        print("no judgments to roll back")
        return 0
    lines = JUDGMENTS_FILE.read_text().strip().splitlines()
    if not lines:
        print("judgments file is empty")
        return 0
    keep = "\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else "")
    JUDGMENTS_FILE.write_text(keep)
    last = json.loads(lines[-1])
    print(f"rolled back last judgment: score={last['score']} on {last.get('plan','?')}")
    return 0


def cmd_templates() -> int:
    print("Built-in templates:")
    for t in STRATEGY_TEMPLATES:
        print(f"  {t['tag']:<14} risk={t['risk']:<6} best_for={t.get('best_for','-')}")
    print()
    print(f"Auto-detected intent categories: {', '.join(INTENT_KEYWORDS.keys())}")
    print(f"Score thresholds: {json.dumps(SCORE_THRESHOLDS, indent=2)}")
    return 0


def cmd_sim(seed: int, steps: int, strategies: int, cands: int) -> int:
    rng = random.Random(seed)
    stra = ["explore systematically, then commit",
            "minimize steps by combining actions",
            "verify each step before proceeding",
            "use a checkpoint and rollback on failure"]
    acts = ["observe(state)", "pick(target)", "open(container)", "use(tool)", "move(destination)"]
    print(f"== StraTA mock rollout (seed={seed}, steps={steps}, "
          f"strategies={strategies}, cands={cands})")
    best_score = -1.0
    best_stra = ""
    best_traj: list[tuple[int, str, float]] = []
    for s in range(strategies):
        sg = rng.choice(stra)
        for _ in range(cands):
            base = sum(ord(c) for c in sg) % 7 / 10.0
            traj: list[tuple[int, str, float]] = []
            total = 0.0
            for t in range(steps):
                a = rng.choice(acts)
                r = max(0.0, min(1.0, base + rng.uniform(-0.15, 0.2)))
                total += r
                traj.append((t, a, round(r, 3)))
            if total > best_score:
                best_score = total
                best_stra = sg
                best_traj = traj
        print(f"  stra[{s}] '{sg[:40]}'  avg_reward={round(base,3)}")
    print()
    print(f"Best strategy: {best_stra}")
    print(f"Best trajectory reward: {round(best_score, 3)} over {len(best_traj)} steps")
    print("Benchmark note: CPU rollout-sim uses synthetic reward (no real env).")
    print("For real training you need 8x H100 + verl/vLLM + AgentGym env per the paper.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="strata-plan",
                                description=textwrap.dedent(__doc__ or "").strip())
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sample", help="generate N candidate plan cards")
    sp.add_argument("intent")
    sp.add_argument("-n", type=int, default=DEFAULT_N)
    sp.add_argument("-t", "--template", default=None,
                    help="domain template (db-migration, api-design, ...)")
    sp.set_defaults(func=lambda a: cmd_sample(a.intent, a.n, a.template))

    sp = sub.add_parser("pick", help="interactively pick one from a bundle (default: latest)")
    sp.add_argument("bundle", nargs="?", default=None)
    sp.set_defaults(func=lambda a: cmd_pick(a.bundle))

    sp = sub.add_parser("judge", help="judge plan↔outcome alignment")
    sp.add_argument("plan")
    sp.add_argument("outcome", nargs="?", default=None,
                    help="path to outcome file OR inline outcome text")
    sp.add_argument("--outcome", dest="outcome_text", default=None,
                    help="inline outcome text (alternative to positional)")
    sp.add_argument("--score-hint", default=None)
    sp.add_argument("--threshold", type=float, default=None,
                    help="override per-category threshold")
    sp.set_defaults(func=lambda a: cmd_judge(a.plan, a.outcome or a.outcome_text,
                                              a.score_hint, a.threshold))

    sp = sub.add_parser("bundle", help="sample + pick in one call")
    sp.add_argument("intent")
    sp.add_argument("-t", "--template", default=None)
    sp.set_defaults(func=lambda a: cmd_bundle(a.intent, a.template))

    sub.add_parser("status", help="show counts + last judgment")\
        .set_defaults(func=lambda a: cmd_status())

    sp = sub.add_parser("report", help="health summary across judgments")
    sp.add_argument("--last", type=int, default=20)
    sp.set_defaults(func=lambda a: cmd_report(a.last))

    sub.add_parser("rollback", help="remove last judgment entry")\
        .set_defaults(func=lambda a: cmd_rollback())

    sub.add_parser("templates", help="list available templates + thresholds")\
        .set_defaults(func=lambda a: cmd_templates())

    sp = sub.add_parser("rollout-sim", help="CPU mock of hierarchical strategy rollout")
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--steps", type=int, default=4)
    sp.add_argument("--strategies", type=int, default=3)
    sp.add_argument("--cands", type=int, default=3)
    sp.set_defaults(func=lambda a: cmd_sim(a.seed, a.steps, a.strategies, a.cands))

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    return 0 if rc is None else rc


if __name__ == "__main__":
    sys.exit(main())
