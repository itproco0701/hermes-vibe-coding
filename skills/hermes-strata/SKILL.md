---
name: hermes-strata
description: StraTA-style plan sampling and self-judgment for any Hermes agent — before you commit to a plan, sample N strategies, score them against the goal, and pick the best. Use when intent is `plan` / `architect` / `設計` / `approach` / `思路` / `方案`. Compatible with vibe-coding Phase 2 and standalone use.
risk: low
source: derived
date_added: '2026-06-17'
compatibility: Hermes Agent >= 1.0; standalone Python 3.10+; pairs with vibe-coding v2.x
metadata:
  author: aipplaw.zo.computer
  version: 0.1.0
  derived_from: xxyQwQ/StraTA (arXiv 2605.06642)
allowed-tools: Bash, Read, Edit, Glob, Grep

# Portability
portable:
  directory: hermes-strata/
  files:
    - SKILL.md
    - scripts/strata_plan.py
    - scripts/strata_plan
    - references/prompt-templates.md
    - references/vibe-coding-integration.md
---

# Hermes-Strata — Plan Sampling + Self-Judgment

## What This Skill Does

StraTA trains an agent with **explicit strategy sampling** (think first, then act) and **self-judgment** (grade your own plan against the outcome). This skill ports that idea to **inference-time** — no GPU, no training. The agent (you, or any Hermes child) just gets better at thinking.

Three operations:

| Command | What it does | When to use |
|---|---|---|
| `strata-plan sample "<intent>"` | Generate N=3 candidate plans, each from a different angle | Before coding a non-trivial feature |
| `strata-plan judge "<plan>" "<outcome>"` | Score plan↔outcome alignment 0-1 with reasons | After every verify / test run |
| `strata-plan bundle` | Run sample → user-pick → judge after execute, all in one | Drop-in for vibe-coding Phase 2/4/5 |

## Why It Works (the 30-second version)

Most agents do this:

```
intent → plan (one shot) → execute → fail → revise
```

Hermes-Strata forces:

```
intent → strategy₁, strategy₂, strategy₃ → pick best → execute
                                            ↓
                              judge(plan, outcome) → revise or commit
```

Sampling is cheap (one extra LLM call per candidate). Judging surfaces mismatches between what you **said** you'd do and what you **did** — the main source of silent agent bugs.

## Quick Start

### Standalone (any agent)

```bash
# 1. Generate 3 plans
strata-plan sample "Add JWT refresh-token rotation to /api/auth"
# → 3 markdown plans, each with a different angle: rotate-in-place / dual-token / sliding-window

# 2. Pick one (interactive) or auto-pick highest self-scored
strata-plan pick

# 3. After running tests, judge alignment
strata-plan judge plans/20260617-134500-bb.md "3 tests pass; 1 flaky on clock-skew"
# → score 0.74, reason: "plan ignored clock-skew edge case"
```

### With vibe-coding (auto-loaded)

When the user request contains `plan` / `architect` / `設計` / `approach` / `方案` / `思路`, vibe-coding's intent detector now loads `hermes-strata`. Phase 2 then becomes:

```
Phase 2.5 — Strategy Sampling
  ↓ sample 3 plans
  ↓ present summary table (1 line per plan)
  ↓ ask user [1/2/3/edit]
Phase 3 — Execute (unchanged)
Phase 4 — Verify (unchanged)
Phase 4.5 — Self-Judgment
  ↓ judge(plan, test_output)
  ↓ if score < 0.6, feed reason into Phase 5 self-correction
Phase 5 — Self-Correction (unchanged)
```

See `references/vibe-coding-integration.md` for the exact patch.

## The Three Strategies (the meat of the skill)

When you sample, force each candidate into a **different** strategy template. This is the actual StraTA innovation — diverse rollout, not three copies of the same plan.

| Tag | Strategy | When to prefer |
|---|---|---|
| `minimal` | Smallest diff that satisfies intent. Touch as few files as possible. | Bug fix, hot-fix, additive feature |
| `explicit` | Spell out all invariants, edge cases, error paths before coding | API change, auth, data migration, anything user-visible |
| `structural` | Question the current shape — is the right abstraction in place? | Refactor, new module, scaling issue |

**Rule**: at least one of the three samples must use `minimal`, at least one must use `explicit`. The third is your call. This is the user's "diverse strategy rollout" — the diversity comes from forcing different framings, not different phrasings.

## Self-Judgment Rubric

The judge gives a 0-1 score and 1-2 sentences. Use this rubric:

| Score | Meaning | Action |
|---|---|---|
| 0.0–0.3 | Plan ignored critical constraint, or outcome contradicts the plan | Revise plan, don't tweak code |
| 0.4–0.6 | Plan partially followed; some steps missed | Add the missed steps to plan, re-execute |
| 0.7–0.85 | Plan followed, minor gaps | Light revision next iteration |
| 0.86–1.0 | Plan matched outcome; alignment clean | Commit, log to mistake journal as "good pattern" |

The score is a **plan↔outcome alignment** score, not a quality score. A plan can score 1.0 on a terrible idea — the rubric is "did you do what you said."

## Failure Modes to Watch For

- **Sampling collapse**: all 3 plans look the same. → Force re-roll with explicit `minimal` / `explicit` / `structural` tags.
- **Judge inflation**: scores always 0.9+. → Require a "missed step" bullet even on 1.0 scores. If none, that's data — log it.
- **Self-judgment without context**: judging plan against a 1-line outcome is noise. Pass full test output, error messages, git diff.
- **Re-plan churn**: if strategy A wins, plan B is "wasted" — that's fine, it costs ~1 LLM call and prevents the worse plan going in.

## Files

```
hermes-strata/
├── SKILL.md                         ← this file
├── scripts/
│   ├── strata_plan                  ← bash wrapper
│   └── strata_plan.py               ← CLI: sample / pick / judge / bundle
├── references/
│   ├── prompt-templates.md          ← copy-paste prompt fragments
│   └── vibe-coding-integration.md   ← exact patch to SKILL.md + vibe_loop.py
└── assets/
    └── strategy-cards.md            ← 1-page printable reference
```

## Dependencies

- Python 3.10+ (stdlib only)
- `strata` parent skill (this is the inference-time counterpart to the research training framework)
- vibe-coding v2.x (optional — for auto-loading)

## Exit Criteria

| Outcome | Condition |
|---|---|
| Use | Plans are non-trivial, multi-file, or touch auth/data/architecture |
| Skip | Single-line fix, single-file typo, trivial config change |
| Escalate | Sampling produces 3 nearly-identical plans twice in a row — go ask the user |
