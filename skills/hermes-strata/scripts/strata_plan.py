#!/usr/bin/env python3
"""strata-plan — StraTA-style plan sampling + self-judging for Hermes.

v2.5 — Generalization hardening (7 fixes):
  • CJK keyword aliasing for intent routing (HIGH)
  • Non-interactive pick: --auto-select [first|best|random] (HIGH)
  • test-first / docs-driven / component-first templates (MEDIUM)
  • .hermes/strata-config.json project-level config (MEDIUM)
  • strata-plan recalibrate — auto-suggest thresholds from judgments (MEDIUM)
  • Composite intent split on "and"/"also"/"並且"/"同時"/"以及" (LOW)
  • report --format [text|json|csv] for CI integration (LOW)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import re
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PLANS_DIR = Path(".strata-plans")
JUDGMENTS_FILE = PLANS_DIR / "judgments.jsonl"
CONFIG_PATHS = [
    Path(".hermes/strata-config.json"),
    Path(".strata-config.json"),
]
DEFAULT_N = 3

# ─────────────────────────────────────────────
# CJK + EN keyword aliases for intent routing
# ─────────────────────────────────────────────
INTENT_KEYWORD_ALIASES: dict[str, list[str]] = {
    "db":        ["db", "database", "schema", "migration", "sql", "postgres", "mysql",
                  "資料庫", "架構", "結構", "表", "表格", "スキーマ", "データベース",
                  "데이터베이스", "스키마"],
    "migration": ["migrate", "migration", "backfill",
                  "遷移", "遷徙", "搬遷", "マイグレーション", "移行",
                  "마이그레이션", "이전"],
    "api":       ["api", "endpoint", "route", "rest", "graphql", "controller",
                  "介面", "接口", "端點", "路由", "コントローラー", "エンドポイント",
                  "엔드포인트", "라우트", "API"],
    "perf":      ["perf", "performance", "slow", "latency", "benchmark", "optim",
                  "效能", "性能", "慢", "延遲", "最適化", "ベンチマーク",
                  "성능", "최적화"],
    "test":      ["test", "spec", "coverage", "pytest", "jest", "vitest",
                  "測試", "測验", "テスト", "커버리지", "테스트"],
    "fix":       ["fix", "bug", "broken", "wrong", "error", "hotfix",
                  "修復", "修bug", "錯誤", "出错", "バグ", "修正",
                  "버그", "수정"],
    "debug":     ["debug", "diagnose", "trace", "investigate",
                  "除錯", "調試", "排查", "追跡",
                  "디버그", "디버깅", "추적"],
    "refactor":  ["refactor", "cleanup", "tidy", "reorganize",
                  "重構", "重写", "整理", "重构",
                  "リファクタ", "리팩토링"],
    "rewrite":   ["rewrite", "redesign", "rebuild",
                  "重寫", "重做", "重新設計", "再構築",
                  "리라이트", "재작성"],
    "docs":      ["doc", "docs", "documentation", "readme", "comment", "jsdoc",
                  "文件", "文檔", "說明", "ドキュメント", "コメント",
                  "문서", "문서화"],
    "frontend":  ["frontend", "ui", "ux", "component", "page", "view",
                  "前端", "界面", "頁面", "组件",
                  "フロントエンド", "コンポーネント",
                  "프론트엔드", "컴포넌트"],
}

CJK_TRANSLATION = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+")


def _normalize_intent(intent: str) -> str:
    return CJK_TRANSLATION.sub(" ", intent).strip()


def _detect_intent_category(intent: str) -> str:
    """Score each known category by counting alias hits in the intent text.
    Returns the best-scoring category, or 'default' if nothing matched.

    v2.5: normalized + alias-aware so CJK intents route correctly.
    """
    text_lower = intent.lower()
    candidates: list[tuple[str, int]] = []
    for cat, aliases in INTENT_KEYWORD_ALIASES.items():
        hits = [a for a in aliases if a.lower() in text_lower]
        if hits:
            candidates.append((cat, len(hits), hits))
    if not candidates:
        return "default"
    # Tie-breaker order: higher category priority wins, then longer alias hit,
    # then alphabetical. Category priority encodes domain specificity:
    # migration > db > perf > api > test > frontend > fix > debug > refactor > rewrite > docs.
    category_priority = {
        "migration": 100, "db": 90, "perf": 85, "api": 80,
        "test": 70, "frontend": 65, "fix": 55, "debug": 54,
        "refactor": 45, "rewrite": 44, "docs": 40,
    }
    candidates.sort(key=lambda x: (
        -x[1],                                         # score desc
        -category_priority.get(x[0], 0),              # category priority desc
        -max(len(h) for h in x[2]),                   # longest alias hit desc
        x[0],                                          # alphabetical asc
    ))
    return candidates[0][0]


# ─────────────────────────────────────────────
# Project-level config (.hermes/strata-config.json)
# ─────────────────────────────────────────────
DEFAULT_CONFIG: dict[str, Any] = {
    "threshold_overrides": {},
    "default_n_cards": 3,
    "auto_select": None,            # None | "first" | "best" | "random"
    "auto_select_min_n": 5,         # min judgments before "best" becomes reliable
    "default_template": None,       # None = auto-detect
    "excluded_keywords": [],        # intent terms that should force "default"
    "report_last_n": 20,
    "calibration_min_samples": 5,   # min judgments per category before recalibrate
    "calibration_quantile": 0.25,   # P25 + small margin → suggested threshold
}


def _load_config(project_path: Path | None = None) -> dict[str, Any]:
    base = Path(project_path) if project_path else Path.cwd()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    for p in CONFIG_PATHS:
        full = base / p
        if full.exists():
            try:
                user_cfg = json.loads(full.read_text())
                if isinstance(user_cfg, dict):
                    for k, v in user_cfg.items():
                        if k == "threshold_overrides" and isinstance(v, dict):
                            cfg["threshold_overrides"].update(v)
                        elif k in cfg:
                            cfg[k] = v
            except (json.JSONDecodeError, OSError):
                pass
    return cfg


def _save_config(cfg: dict[str, Any], project_path: Path | None = None) -> Path:
    base = Path(project_path) if project_path else Path.cwd()
    target = base / CONFIG_PATHS[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    return target


# ─────────────────────────────────────────────
# Templates — extended with test-first / docs-driven / component-first (v2.5)
# ─────────────────────────────────────────────
@dataclass
class Template:
    tag: str
    one_liner: str
    tradeoff: str
    risk: str
    best_for: list[str]
    seed_steps: list[str]


TEMPLATES: dict[str, Template] = {
    "minimal": Template(
        "minimal", "Touch the fewest files and add the least new code; reuse what's there.",
        "Fast and safe, but may force a slightly awkward fit if existing abstractions don't quite line up.",
        "low", ["fix", "debug", "docs"],
        [
            "Read the existing test that covers the affected behaviour",
            "Make the smallest change that makes the failing case pass",
            "Run the relevant tests; do not add new abstractions",
        ],
    ),
    "structured": Template(
        "structured", "Add a thin layer (helper / middleware / new module) to keep changes isolated.",
        "Clean separation, easier to test; costs a small amount of new surface area.",
        "medium", ["api", "perf", "test"],
        [
            "Identify the seam where the new concern should live",
            "Introduce a narrow module / helper that owns the concern",
            "Wire callers to the new module and keep the old path behind it",
        ],
    ),
    "rewrite": Template(
        "rewrite", "Refactor the affected area to make the change natural instead of fighting it.",
        "Better long-term shape; risks scope creep and longer review cycle.",
        "high", ["refactor", "rewrite", "migration"],
        [
            "Map the current shape: what depends on what",
            "Decide the target shape and migration order",
            "Rewrite behind a compatibility shim; flip callers in a second pass",
        ],
    ),
    "transactional": Template(
        "transactional", "DB-first: change is a schema migration plus idempotent backfill, wrapped in a single transaction.",
        "Safest for data correctness; couples release to migration tooling.",
        "medium", ["db", "migration"],
        [
            "Write a forward-only schema change with a documented rollback",
            "Add idempotent backfill in the same migration",
            "Verify with a representative production-shape dataset before merging",
        ],
    ),
    "contract-first": Template(
        "contract-first", "API-first: design the request/response contract (types, errors, status codes), then implement against it.",
        "Forces clean contracts before code; needs discipline to keep types in sync with docs.",
        "medium", ["api"],
        [
            "Write the request/response schema (or types) and document each field",
            "Define failure modes (status codes, error envelopes) up front",
            "Implement the handler against the contract; add a contract test",
        ],
    ),
    "benchmark-first": Template(
        "benchmark-first", "Performance-first: define a reproducible benchmark + budget, then optimize against it.",
        "Prevents 'feels faster' guessing; needs a clean test environment.",
        "low", ["perf"],
        [
            "Write a representative benchmark with realistic input size",
            "Capture baseline numbers and set a budget",
            "Iterate changes against the benchmark; commit numbers in the PR",
        ],
    ),
    "test-first": Template(
        "test-first", "Testing-first: choose a coverage strategy (happy-path-first / failure-mode-first / coverage-first), then write tests that pin behaviour.",
        "Pins behaviour before code; requires discipline to keep tests honest.",
        "low", ["test"],
        [
            "Decide coverage strategy: happy-path / failure-mode / coverage-first",
            "Write tests for the highest-leverage behaviours first",
            "Iterate against the failing tests until they pass",
        ],
    ),
    "docs-driven": Template(
        "docs-driven", "Documentation-first: choose audience (reader-first / structure-first / example-driven), then write the doc that explains intent before code.",
        "Forces clear intent; can become stale if not co-located with code.",
        "low", ["docs"],
        [
            "Identify the primary reader and what they need to do after reading",
            "Pick a structure strategy: reader-first / structure-first / example-driven",
            "Write a complete first draft; review for gaps before any code change",
        ],
    ),
    "component-first": Template(
        "component-first", "UI-first: start from the component contract (props, states, a11y), then layout, then composition.",
        "Prevents layout-then-logic drift; requires design tokens / headless primitives.",
        "medium", ["frontend"],
        [
            "Define the component contract: props, states, a11y roles",
            "Build a layout skeleton with semantic tokens",
            "Compose into the page and verify responsive + a11y behaviour",
        ],
    ),
}


def _resolve_template(template: str | None, intent: str, category: str) -> list[dict[str, Any]]:
    """Return N template cards. If template is given, return one template's seed steps once.
    If auto, pick templates whose best_for matches category, in stable order."""
    cats = [category] if category != "default" else ["fix"]
    if template:
        if template == "list":
            return [asdict(t) for t in TEMPLATES.values()]
        if template not in TEMPLATES:
            print(f"⚠️ unknown template '{template}', falling back to auto", file=sys.stderr)
            template = None
    if template:
        t = TEMPLATES[template]
        return [asdict(t)]
    out = []
    for t in TEMPLATES.values():
        if any(c in t.best_for for c in cats):
            out.append(asdict(t))
    return out[:5] or [asdict(TEMPLATES["minimal"])]


def _seed_steps_for(tag: str, intent: str) -> list[str]:
    t = TEMPLATES.get(tag)
    if not t:
        return ["(template has no seed steps)"]
    return list(t.seed_steps)


# ─────────────────────────────────────────────
# Per-category thresholds (overridable via config)
# ─────────────────────────────────────────────
DEFAULT_THRESHOLDS: dict[str, float] = {
    "refactor": 0.65, "rewrite": 0.55, "fix": 0.45, "debug": 0.45,
    "api": 0.70, "db": 0.75, "migration": 0.80, "perf": 0.60,
    "test": 0.60, "docs": 0.50, "frontend": 0.60, "default": 0.60,
}


def _threshold_for(category: str, overrides: dict[str, float]) -> float:
    return overrides.get(category) or DEFAULT_THRESHOLDS.get(category) or DEFAULT_THRESHOLDS["default"]


# ─────────────────────────────────────────────
# Composite intent split (LOW)
# ─────────────────────────────────────────────
SPLIT_RE = re.compile(
    r"\s+(?:and also|and then|also|then|並且|並且要|同時|以及|還要|以及要|以及同時|同時候|그리고|및|また|そして)\s+",
    re.IGNORECASE,
)


def _split_composite_intent(intent: str) -> list[str]:
    parts = SPLIT_RE.split(intent)
    parts = [p.strip(" ，,。. ") for p in parts if p.strip()]
    return parts if len(parts) > 1 else [intent.strip()]


# ─────────────────────────────────────────────
# PlanCard / Bundle / Judgment data
# ─────────────────────────────────────────────
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
    intent_category: str = "default"
    threshold: float = 0.6
    steps_total: int = 0
    steps_addressed: int = 0


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_plans_dir() -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Step extraction — robust to bullet lists + paragraphs (carried from v2.4)
# ─────────────────────────────────────────────
STEP_OPENER = re.compile(
    r"^\s*(?:"
    r"\d+[.)]\s+"
    r"|[a-z][.)]\s+"
    r"|[-*+•]\s+"
    r")",
    re.IGNORECASE,
)


def _extract_steps(plan: str) -> list[str]:
    steps: list[str] = []
    in_section = False
    for line in plan.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            in_section = line.strip("#").strip().lower().startswith(("implementation", "steps", "step"))
            continue
        if STEP_OPENER.match(line):
            text = STEP_OPENER.sub("", line).strip()
            text = re.sub(r"\[[ xX]\]\s*", "", text).strip()
            if text:
                steps.append(text)
    return steps or [line.strip() for line in plan.splitlines() if line.strip()][:5]


# ─────────────────────────────────────────────
# Judge — same logic as v2.4 but takes config overrides
# ─────────────────────────────────────────────
def _judge(plan: str, outcome: str, score_hint: str | None,
           intent: str = "", threshold: float | None = None) -> Judgment:
    steps = _extract_steps(plan)
    category = _detect_intent_category(intent) if intent else "default"
    cfg = _load_config()
    eff_threshold = threshold if threshold is not None else _threshold_for(category, cfg["threshold_overrides"])
    if not steps:
        return Judgment(score=0.5, reason="plan had no recognizable steps — nothing to verify",
                        next_action="add atomic steps to plan",
                        intent_category=category, threshold=eff_threshold)
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
    if score < eff_threshold:
        nxt = "revise plan to cover missed steps, re-execute"
    elif score < max(eff_threshold + 0.2, 0.86):
        nxt = "log the gap, continue; address in next iteration"
    else:
        nxt = "commit; record plan↔outcome pair as 'good pattern' in mistake journal"
    return Judgment(
        score=score,
        reason=f"addressed {addressed}/{len(steps)} steps; category={category}",
        missed_steps=missed,
        next_action=nxt,
        intent_category=category,
        threshold=eff_threshold,
        steps_total=len(steps),
        steps_addressed=addressed,
    )


# ─────────────────────────────────────────────
# Mistake Journal bridge
# ─────────────────────────────────────────────
MISTAKE_JOURNAL = ".vibe-mistakes.json"


def _load_mistake_journal(project_path: Path) -> dict:
    mf = project_path / MISTAKE_JOURNAL
    if mf.exists():
        try:
            return json.loads(mf.read_text())
        except json.JSONDecodeError:
            pass
    return {"project": project_path.name, "created_at": _now_iso(), "mistakes": []}


def _save_mistake_journal(project_path: Path, journal: dict) -> None:
    mf = project_path / MISTAKE_JOURNAL
    mf.write_text(json.dumps(journal, indent=2, ensure_ascii=False))


def _append_mistake_journal(project_path: Path, j: Judgment, plan_path: str, intent: str) -> bool:
    try:
        journal = _load_mistake_journal(project_path)
        category = f"strata_{j.intent_category}"
        context = f"strata-plan judge: intent={intent[:80]!r}"
        existing = next((m for m in journal["mistakes"]
                         if m["category"] == category and m.get("context", "")[:80] == context[:80]), None)
        if existing:
            existing["occurrence_count"] = existing.get("occurrence_count", 1) + 1
            existing["last_occurred"] = _now_iso()
            existing["related_files"] = list({*existing.get("related_files", []), plan_path})
        else:
            journal["mistakes"].append({
                "id": hashlib.md5(f"{category}:{context}:{_now_iso()}".encode()).hexdigest()[:12],
                "category": category,
                "context": context,
                "mistake": f"score {j.score} below threshold {j.threshold} for category {j.intent_category}",
                "lesson": "Review missed_steps in judgments.jsonl and tighten plan or raise threshold",
                "related_files": [plan_path],
                "timestamp": _now_iso(),
                "session_id": _ts(),
                "occurrence_count": 1,
                "last_occurred": _now_iso(),
            })
        _save_mistake_journal(project_path, journal)
        print(f"Logged to {project_path / MISTAKE_JOURNAL} as '{category}'")
        return True
    except Exception as exc:  # pragma: no cover — best-effort bridge
        print(f"⚠️ Mistake Journal bridge failed: {exc}", file=sys.stderr)
        return False


def _bridge_to_mistake_journal(project_path: Path, j: Judgment, plan_path: str, intent: str) -> bool:
    if not j.missed_steps or j.score >= j.threshold:
        return False
    return _append_mistake_journal(project_path, j, plan_path, intent)


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────
def cmd_sample(intent: str, n: int, template: str | None) -> int:
    cfg = _load_config()
    if n is None or n == 0:
        n = cfg["default_n_cards"]
    excluded = [k.lower() for k in cfg.get("excluded_keywords", [])]
    if any(k in intent.lower() for k in excluded):
        print(f"⚠️ intent contains excluded keyword — forcing default category")
        category = "default"
    else:
        category = _detect_intent_category(intent)
    template = template or cfg.get("default_template")
    cards_dicts = _resolve_template(template, intent, category)
    if template and template != "list":
        cards_dicts = cards_dicts * max(1, n)
    elif not template:
        cards_dicts = cards_dicts[:max(1, n)] or [asdict(TEMPLATES["minimal"])]
    cards = [
        PlanCard(
            tag=c["tag"], one_liner=c["one_liner"], tradeoff=c["tradeoff"], risk=c["risk"],
            steps=_seed_steps_for(c["tag"], intent),
        )
        for c in cards_dicts
    ]
    _ensure_plans_dir()
    bundle = Bundle(intent=intent, created_at=_now_iso(), cards=cards)
    bp = PLANS_DIR / f"bundle-{_ts()}-{hashlib.md5(intent.encode()).hexdigest()[:6]}.json"
    bp.write_text(json.dumps(asdict(bundle), ensure_ascii=False, indent=2))
    print(f"intent_category: {category}")
    print(f"template: {template or 'auto'}")
    print(f"bundle: {bp.name}")
    for i, c in enumerate(cards, 1):
        print(f"  [{i}] {c.tag:<10} risk={c.risk:<6} {c.one_liner[:60]}")
    return 0


def _load_bundle(bundle_arg: str | None) -> Path:
    if bundle_arg:
        p = Path(bundle_arg).name
        candidate = PLANS_DIR / p
        if candidate.exists():
            return candidate
        if Path(bundle_arg).exists():
            return Path(bundle_arg)
        sys.exit(f"bundle not found: {bundle_arg}")
    bundles = sorted(PLANS_DIR.glob("bundle-*.json"))
    if not bundles:
        sys.exit("no sample bundles in .strata-plans/ — run `strata-plan sample <intent>` first")
    return bundles[-1]


def _load_bundle_obj(bp: Path) -> Bundle:
    data = json.loads(bp.read_text())
    cards = [PlanCard(**c) for c in data["cards"]]
    return Bundle(intent=data["intent"], created_at=data["created_at"], cards=cards)


def _auto_select_card(bundle: Bundle, mode: str, project_path: Path | None = None) -> PlanCard:
    """Pick a card without user interaction. mode ∈ {first, best, random}."""
    cfg = _load_config(project_path or Path.cwd())
    if mode == "first" or not bundle.cards:
        return bundle.cards[0]
    if mode == "random":
        return random.Random(_ts()).choice(bundle.cards)
    if mode == "best":
        # Look up historical avg score per template tag
        if not JUDGMENTS_FILE.exists():
            print("⚠️ no judgments yet — falling back to 'first'", file=sys.stderr)
            return bundle.cards[0]
        rows = [json.loads(l) for l in JUDGMENTS_FILE.read_text().strip().splitlines() if l.strip()]
        min_n = cfg.get("auto_select_min_n", 5)
        by_tag: dict[str, list[float]] = {}
        for r in rows:
            plan_path = Path(r.get("plan", ""))
            tag = "(unknown)"
            if plan_path.exists():
                ptext = plan_path.read_text()
                m = re.search(r"^##\s+Strategy\s*\n+\x60([\w-]+)\x60", ptext, re.MULTILINE)
                if m:
                    tag = m.group(1)
            by_tag.setdefault(tag, []).append(r.get("score", 0.0))
        best, best_avg = bundle.cards[0], -1.0
        for c in bundle.cards:
            samples = by_tag.get(c.tag, [])
            if len(samples) < min_n:
                continue
            avg = sum(samples) / len(samples)
            if avg > best_avg:
                best, best_avg = c, avg
        if best_avg < 0:
            print(f"⚠️ no template has ≥{min_n} samples — falling back to 'first'", file=sys.stderr)
            return bundle.cards[0]
        print(f"  auto-select=best picked '{best.tag}' (avg {best_avg:.2f} over {len(by_tag[best.tag])} samples)")
        return best
    print(f"⚠️ unknown auto-select mode '{mode}' — falling back to 'first'", file=sys.stderr)
    return bundle.cards[0]


def cmd_pick(bundle_arg: str | None, auto_select: str | None,
             non_interactive: bool, intent_override: str | None) -> int:
    cfg = _load_config()
    bp = _load_bundle(bundle_arg)
    bundle = _load_bundle_obj(bp)
    print(f"== Bundle: {bp.name}")
    print(f"intent: {bundle.intent}")
    print(f"created: {bundle.created_at}")
    print()
    if auto_select or non_interactive or cfg.get("auto_select"):
        mode = auto_select or cfg.get("auto_select") or "first"
        picked = _auto_select_card(bundle, mode)
        print(f"  (non-interactive auto-select={mode})")
    else:
        for i, c in enumerate(bundle.cards, 1):
            print(f"  [{i}] {c.tag:<14} risk={c.risk:<6} {c.one_liner[:60]}")
        print()
        try:
            choice = input("Pick 1/2/3 (or 'q' to abort): ").strip()
        except EOFError:
            print("\n⚠️ stdin closed — falling back to --auto-select=first")
            picked = bundle.cards[0]
        else:
            if choice.lower() == "q":
                return 0
            if not choice.isdigit() or not (0 <= int(choice) - 1 < len(bundle.cards)):
                sys.exit("invalid input")
            picked = bundle.cards[int(choice) - 1]
    intent = intent_override or bundle.intent
    plan_path = PLANS_DIR / f"plan-{_ts()}-{picked.tag}.md"
    plan_path.write_text(_render_plan_md(intent, picked))
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


def cmd_judge(plan: str, outcome_arg: str | None, score_hint: str | None,
              threshold: float | None, project_path: str | None) -> int:
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
    proj = Path(project_path) if project_path else Path.cwd()
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
    if j.score < j.threshold:
        print(f"Score {j.score} < threshold {j.threshold} — bridge to Mistake Journal will fire.")
        _bridge_to_mistake_journal(proj, j, str(plan_path), intent)
    else:
        print("Score >= threshold — no Mistake Journal entry needed.")
    return 0


def cmd_bundle(intent: str, template: str | None) -> int:
    cfg = _load_config()
    n = cfg["default_n_cards"]
    if cmd_sample(intent, n, template) != 0:
        return 1
    return cmd_pick(None, auto_select=cfg.get("auto_select"),
                    non_interactive=bool(cfg.get("auto_select")),
                    intent_override=intent)


def cmd_status() -> int:
    cfg = _load_config()
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
    print(f"config: {CONFIG_PATHS[0]} exists={(CONFIG_PATHS[0]).exists()}")
    return 0


def cmd_report(last: int, fmt: str) -> int:
    """Health summary. fmt ∈ {text, json, csv}."""
    if not JUDGMENTS_FILE.exists():
        if fmt == "json":
            print(json.dumps({"error": "no judgments yet"}))
        else:
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
    summary = {
        "total": len(rows),
        "below_threshold": below,
        "below_threshold_rate": round(below / max(1, len(rows)), 3),
        "categories": {
            cat: {
                "count": len(scores),
                "avg": round(sum(scores) / len(scores), 3),
                "min": round(min(scores), 3),
                "max": round(max(scores), 3),
                "below_threshold_rate": round(
                    sum(1 for s in scores if s < DEFAULT_THRESHOLDS.get(cat, 0.6)) / len(scores), 3
                ),
            }
            for cat, scores in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))
        },
    }
    if fmt == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["category", "count", "avg", "min", "max", "below_threshold_rate"])
        for cat, stats in summary["categories"].items():
            w.writerow([cat, stats["count"], stats["avg"], stats["min"], stats["max"], stats["below_threshold_rate"]])
        return 0
    print(f"== StrATA Plan Report — {len(rows)} judgments (last {last or 'all'})")
    print(f"below threshold: {below}/{len(rows)}  ({summary['below_threshold_rate']*100:.0f}%)")
    print()
    print(f"{'category':<12} {'count':>5} {'avg':>6} {'min':>6} {'max':>6}")
    for cat, stats in summary["categories"].items():
        print(f"{cat:<12} {stats['count']:>5} {stats['avg']:>6.2f} "
              f"{stats['min']:>6.2f} {stats['max']:>6.2f}")
    missed_pool = [m for r in rows if r["score"] < r.get("threshold", 0.6)
                   for m in r.get("missed", [])]
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


def cmd_recalibrate(apply: bool, project_path: str | None) -> int:
    """Suggest per-category thresholds from historical judgments.
    With --apply, write to .hermes/strata-config.json."""
    proj = Path(project_path) if project_path else Path.cwd()
    cfg = _load_config(proj)
    if not JUDGMENTS_FILE.exists():
        print("no judgments yet — nothing to calibrate", file=sys.stderr)
        return 1
    rows = [json.loads(l) for l in JUDGMENTS_FILE.read_text().strip().splitlines() if l.strip()]
    min_samples = cfg.get("calibration_min_samples", 5)
    quantile = cfg.get("calibration_quantile", 0.25)
    by_cat: dict[str, list[float]] = {}
    for r in rows:
        by_cat.setdefault(r.get("intent_category", "default"), []).append(r["score"])
    suggestions: dict[str, dict[str, Any]] = {}
    for cat, scores in sorted(by_cat.items()):
        if len(scores) < min_samples:
            continue
        s = sorted(scores)
        idx = max(0, min(len(s) - 1, int(len(s) * quantile) - 1))
        suggested = round(s[idx] - 0.05, 2)
        suggested = max(0.30, min(0.90, suggested))
        current = cfg["threshold_overrides"].get(cat) or DEFAULT_THRESHOLDS.get(cat, 0.6)
        suggestions[cat] = {
            "samples": len(scores),
            "current": current,
            "suggested": suggested,
            "p25": round(s[idx], 3),
            "delta": round(suggested - current, 3),
        }
    if not suggestions:
        print(f"no category has ≥{min_samples} samples yet — collect more judgments first", file=sys.stderr)
        return 1
    print(f"{'category':<12} {'samples':>7} {'current':>8} {'p25':>6} {'suggested':>10} {'delta':>7}")
    for cat, s in suggestions.items():
        print(f"{cat:<12} {s['samples']:>7} {s['current']:>8.2f} {s['p25']:>6.2f} "
              f"{s['suggested']:>10.2f} {s['delta']:>+7.2f}")
    if apply:
        for cat, s in suggestions.items():
            cfg["threshold_overrides"][cat] = s["suggested"]
        cfg["last_calibrated"] = _now_iso()
        target = _save_config(cfg, proj)
        print(f"\n✅ Applied to {target}")
        history = proj / ".hermes" / "strata-calibration-history.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        hist = json.loads(history.read_text()) if history.exists() else {"entries": []}
        hist["entries"].append({"timestamp": _now_iso(), "applied": {
            cat: s["suggested"] for cat, s in suggestions.items()
        }})
        history.write_text(json.dumps(hist, indent=2, ensure_ascii=False))
        print(f"   history appended to {history}")
    else:
        print("\n(dry-run only — pass --apply to write to .hermes/strata-config.json)")
    return 0


def cmd_rollback() -> int:
    if not JUDGMENTS_FILE.exists():
        print("no judgments file — nothing to rollback", file=sys.stderr)
        return 1
    lines = JUDGMENTS_FILE.read_text().strip().splitlines()
    if not lines:
        print("judgments file empty — nothing to rollback", file=sys.stderr)
        return 1
    removed = lines.pop()
    JUDGMENTS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))
    last = json.loads(removed)
    print(f"Removed last judgment: score={last['score']} category={last.get('intent_category','?')}")
    return 0


def cmd_templates() -> int:
    print("Built-in templates:")
    for t in TEMPLATES.values():
        print(f"  {t.tag:<14} risk={t.risk:<6} best_for={','.join(t.best_for)}")
    print()
    print("Auto-detected intent categories:")
    print("  " + ", ".join(sorted(INTENT_KEYWORD_ALIASES.keys())))
    print()
    print("Score thresholds (default; config may override):")
    print(json.dumps(DEFAULT_THRESHOLDS, indent=2))
    return 0


def cmd_config_show() -> int:
    print(json.dumps(_load_config(), indent=2, ensure_ascii=False))
    return 0


def cmd_config_set(key: str, value: str) -> int:
    cfg = _load_config()
    if key not in DEFAULT_CONFIG and key != "threshold_overrides":
        sys.exit(f"unknown config key: {key}")
    if key == "default_n_cards":
        cfg["default_n_cards"] = int(value)
    elif key == "auto_select":
        cfg["auto_select"] = None if value == "none" else value
    elif key == "auto_select_min_n":
        cfg["auto_select_min_n"] = int(value)
    elif key == "excluded_keywords":
        cfg["excluded_keywords"] = [v.strip() for v in value.split(",") if v.strip()]
    elif key.startswith("threshold_overrides."):
        _, cat = key.split(".", 1)
        cfg["threshold_overrides"][cat] = float(value)
    else:
        cfg[key] = value
    target = _save_config(cfg)
    print(f"✅ wrote {key}={value} to {target}")
    return 0


def cmd_sim(seed: int, steps: int, strategies: int, cands: int) -> int:
    """CPU mock of hierarchical strategy rollout (benchmark/validation)."""
    rng = random.Random(seed)
    strategies = max(1, strategies)
    cands = max(1, cands)
    steps = max(1, steps)
    print(f"== StrATA mock rollout (seed={seed}, steps={steps}, strategies={strategies}, cands={cands}) ==")
    print(f"Benchmark note: CPU rollout-sim uses synthetic reward (no real env).")
    print(f"For real training you need 8x H100 + verl/vLLM + AgentGym env per the paper.")
    print()
    best_stra, best_score, best_traj = "", -1.0, []
    for s in range(strategies):
        stra = f"stra-{s}-seed{seed}"
        for c in range(cands):
            score = rng.uniform(0.0, 1.0)
            traj = [(t, rng.uniform(0.0, 1.0)) for t in range(steps)]
            if score > best_score:
                best_stra, best_score, best_traj = stra, score, traj
        print(f"  {stra}  cands={cands}  best_in_group={score:.3f}")
    print()
    print(f"Best strategy: {best_stra}")
    print(f"Best trajectory reward: {round(best_score, 3)} over {len(best_traj)} steps")
    return 0


# ─────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="strata-plan",
                                description=textwrap.dedent(__doc__ or "").strip())
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sample", help="generate N candidate plan cards")
    sp.add_argument("intent")
    sp.add_argument("-n", type=int, default=0)  # 0 = defer to config["default_n_cards"]
    sp.add_argument("-t", "--template", default=None)
    sp.set_defaults(func=lambda a: cmd_sample(a.intent, a.n, a.template))

    sp = sub.add_parser("pick", help="interactively pick one from a bundle")
    sp.add_argument("bundle", nargs="?", default=None)
    sp.add_argument("--auto-select", choices=["first", "best", "random"], default=None,
                    help="non-interactive pick (HIGH priority gap fix)")
    sp.add_argument("--non-interactive", action="store_true",
                    help="alias for --auto-select=first (CI/CD use)")
    sp.add_argument("--intent", dest="intent_override", default=None,
                    help="override the bundle's intent when rendering the plan")
    sp.set_defaults(func=lambda a: cmd_pick(a.bundle, a.auto_select,
                                             a.non_interactive, a.intent_override))

    sp = sub.add_parser("judge", help="judge plan↔outcome alignment")
    sp.add_argument("plan")
    sp.add_argument("outcome", nargs="?", default=None)
    sp.add_argument("--outcome", dest="outcome_text", default=None)
    sp.add_argument("--score-hint", default=None)
    sp.add_argument("--threshold", type=float, default=None)
    sp.add_argument("--project-path", default=None)
    sp.set_defaults(func=lambda a: cmd_judge(a.plan, a.outcome or a.outcome_text,
                                              a.score_hint, a.threshold, a.project_path))

    sp = sub.add_parser("bundle", help="sample + pick in one call")
    sp.add_argument("intent")
    sp.add_argument("-t", "--template", default=None)
    sp.add_argument("--auto-select", choices=["first", "best", "random"], default=None)
    sp.add_argument("--non-interactive", action="store_true")
    sp.set_defaults(func=lambda a: cmd_bundle_intent(a.intent, a.template,
                                                      a.auto_select, a.non_interactive))

    sub.add_parser("status", help="show counts + last judgment")\
        .set_defaults(func=lambda a: cmd_status())

    sp = sub.add_parser("report", help="health summary across judgments")
    sp.add_argument("--last", type=int, default=20)
    sp.add_argument("--format", choices=["text", "json", "csv"], default="text",
                    help="text (default) | json | csv — for CI integration")
    sp.set_defaults(func=lambda a: cmd_report(a.last, a.format))

    sub.add_parser("rollback", help="remove last judgment entry")\
        .set_defaults(func=lambda a: cmd_rollback())

    sub.add_parser("templates", help="list available templates + thresholds")\
        .set_defaults(func=lambda a: cmd_templates())

    sp = sub.add_parser("recalibrate", help="suggest/apply thresholds from judgments (MEDIUM)")
    sp.add_argument("--apply", action="store_true",
                    help="write suggested thresholds to .hermes/strata-config.json")
    sp.add_argument("--project-path", default=None)
    sp.set_defaults(func=lambda a: cmd_recalibrate(a.apply, a.project_path))

    sp = sub.add_parser("config", help="show/set project-level config (MEDIUM)")
    sp_sub = sp.add_subparsers(dest="config_cmd", required=True)
    sp_sub.add_parser("show").set_defaults(func=lambda a: cmd_config_show())
    sp_sp = sp_sub.add_parser("set")
    sp_sp.add_argument("key")
    sp_sp.add_argument("value")
    sp_sp.set_defaults(func=lambda a: cmd_config_set(a.key, a.value))

    sp = sub.add_parser("rollout-sim", help="CPU mock of hierarchical strategy rollout")
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--steps", type=int, default=4)
    sp.add_argument("--strategies", type=int, default=3)
    sp.add_argument("--cands", type=int, default=3)
    sp.set_defaults(func=lambda a: cmd_sim(a.seed, a.steps, a.strategies, a.cands))

    return p


def cmd_bundle_intent(intent: str, template: str | None,
                      auto_select: str | None, non_interactive: bool) -> int:
    cfg = _load_config()
    n = cfg["default_n_cards"]
    if cmd_sample(intent, n, template) != 0:
        return 1
    mode = auto_select or cfg.get("auto_select")
    if non_interactive and not mode:
        mode = "first"
    return cmd_pick(None, auto_select=mode, non_interactive=non_interactive,
                    intent_override=intent)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rc = args.func(args)
    return 0 if rc is None else rc


if __name__ == "__main__":
    sys.exit(main())