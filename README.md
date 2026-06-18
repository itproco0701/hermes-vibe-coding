# hermes-vibe-coding

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill suite for vibe coding —
describe what you want in natural language, and the agent handles repo mapping, planning,
execution, cross-file coordination, self-correction, and git checkpointing.

**v2** closes the gap with [Claude Code](https://claude.ai/code) across all 6 core dimensions,
while leveraging Hermes's unique cross-session memory advantage. **v2.3+** adds a StraTA-inspired
planning sub-skill that samples multiple strategies before committing to one.

---

## What's new

| Version | What changed |
|---------|--------------|
| **v2.5.0** | `hermes-strata` generalization — CJK intent detection (繁中 / 簡中 / 日本語 / 한국어), project-level config (`.hermes/strata-config.json` or `.vibe-config.json`), non-interactive `--auto-select {first,best,random}`, template system (`db-migration`, `api-design`, `test-fix`, `perf`, `docs`, `component-first`, `test-first`), category-aware threshold with `threshold_overrides`, confidence-aware auto-select (`auto_select_min_n` gate), `recalibrate` from historical judgments |
| **v2.4.0** | `hermes-strata` hardened — robust step extraction (numbered / lettered / bullet lists), intent-category threshold, judge→Mistake Journal auto-bridge, end-to-end smoke test in `install.sh`, `report` + `templates` + `rollback` subcommands |
| **v2.3.0** | `hermes-strata` sub-skill — StraTA-inspired plan sampling + self-judgment. Auto-loaded when intent contains planning / fix keywords. Wired into `phase_plan()` and `phase_correct()` |
| **v2.2.0** | Mistake Journal with permanent memory + Intent Detection auto-skill loading + 6 sub-skills |
| **v2.0.0** | 7-phase agent loop with LSP, atomic edits, error classifier, git integration |

### Dimension coverage (v2.5)

| Dimension | v1 | v2 | v2.4 | v2.5 |
|-----------|----|----|------|------|
| Repo understanding | Manual `-p` path only | Auto root detection + symbol map + 30min cache | unchanged | unchanged |
| Semantic analysis | Pure grep/find | LSP diagnostics (pyright, tsc, gopls, rust-analyzer) | unchanged | unchanged |
| Cross-file edits | Sequential, no tracking | AST import graph + blast radius + atomic transaction | unchanged | unchanged |
| Error self-correction | Generic retry | 10-type classifier + strategy-matched fix agent | + strata-judge feedback | + per-category threshold |
| Feedback loop | Basic stdout capture | Test + lint + LSP + independent subagent review | unchanged | unchanged |
| Git integration | Not included | Pre-task stash/branch + step commits + PR | unchanged | unchanged |
| Cross-session memory | Via Hermes memory | Structured JSON: conventions, pitfalls, task history | + strata plan↔outcome pairs | + project-level config |
| **Plan sampling** | **None** | **None** | **StraTA: N candidate plans → pick → self-judge → feed gaps to Mistake Journal** | **+ CJK, non-interactive, templates, recalibrate** |

---

## Architecture

```
vibe "<intent>" -p <path>
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  vibe_loop.py  (7-phase agent loop)                 │
│                                                     │
│  Phase 0 ── git-integration    (stash + branch)    │
│  Phase 1 ── repo-explorer      (symbol map + cache)│
│  Phase 2 ── hermes-strata ★    (N candidate plans  │
│              │                → pick → save)        │
│              └─ planning fallback if no strata       │
│  Phase 3 ── atomic-modify      (cross-file edits)  │
│  Phase 4 ── lsp-integration    (semantic verify)   │
│  Phase 5 ── error-recovery     (bounded retry ×3)  │
│              └─ strata-judge (plan↔outcome scoring)│
│  Phase 6 ── git-integration    (structured commit) │
│  Phase 7 ── project-memory     (save task history) │
└─────────────────────────────────────────────────────┘
```

★ = loaded by Intent Detection when intent contains planning / refactor / fix keywords.

---

## Skills

| Skill | Purpose |
|-------|---------|
| `SKILL.md` | Main vibe-coding skill — orchestrates the 7-phase loop |
| `skills/hermes-strata/` | **StraTA-inspired planning**: sample N plan cards, pick one, judge plan↔outcome, auto-bridge to Mistake Journal when score < threshold |
| `skills/lsp-integration.skill.md` | Type-aware diagnostics via pyright / tsc / gopls / rust-analyzer |
| `skills/atomic-modify.skill.md` | Import graph + blast radius + atomic cross-file edits |
| `skills/error-recovery.skill.md` | 10-type error classifier + strategy-matched fix agent |
| `skills/repo-explorer.skill.md` | Auto project root detection + symbol map + caching |
| `skills/git-integration.skill.md` | Pre-task checkpoint, step commits, rollback, PR creation |
| `skills/project-memory.skill.md` | Cross-session conventions, pitfalls, task history |

### `hermes-strata` — what it does

A lightweight, inference-time application of the [StraTA paper](https://arxiv.org/abs/2605.06642) algorithm.
**No model training required** — the pattern is implemented as a planning protocol:

1. **Sample** — `strata-plan sample "<intent>"` generates N candidate plan cards, each with
   a different strategy tag (minimal / structured / rewrite), tradeoff, and risk level.
2. **Pick** — `strata-plan pick` lets you (or the agent) choose one interactively or non-interactively.
3. **Execute** — the picked card is rendered into a markdown plan that `phase_execute` consumes.
4. **Judge** — `strata-plan judge <plan> <outcome>` scores the plan↔outcome alignment using
   robust step extraction (numbered / lettered / bullet lists).
5. **Bridge** — if score < intent-category threshold, the missed steps are written to
   `.vibe-mistakes.json` so future runs see the gap before they start.

The CPU `rollout-sim` mode is a sanity check only — real value comes from running the
sampling + judgment loop in your actual workflow.

#### v2.5.0 — generalization (7 features)

Closes the gaps that showed up when teams with different languages / workflows tried v2.4.0.
All features are **additive + opt-in** — existing v2.4.0 calls and `judgments.jsonl` files still work.

| # | Feature | Solves |
|---|---------|--------|
| 1 | **CJK intent detection** (繁中 / 簡中 / 日本語 / 한국어) | "修 bug 找不到對應 category" |
| 2 | **Project-level config** (`.hermes/strata-config.json` or `.vibe-config.json`) | Hard-coded thresholds in central config |
| 3 | **Non-interactive `--auto-select` modes** (`first` / `best` / `random`) | Interactive prompt blocks CI / Telegram |
| 4 | **Template system** (`db-migration`, `api-design`, `test-fix`, `perf`, `docs`, `component-first`, `test-first`) | Generic templates ignore domain best practices |
| 5 | **Category-aware threshold + `threshold_overrides`** | Single 0.6 for `db` is wrong for `api` |
| 6 | **Confidence-aware auto-select** (`auto_select_min_n` gate) | `best` with n=2 is just noise |
| 7 | **`recalibrate` from historical judgments** | Manual threshold tuning |

Quick example:

```bash
# 1. Init project config
strata-plan init

# 2. Sample with template + non-interactive pick
strata-plan sample "add OAuth to login flow" -t api-design -n 4
strata-plan pick --auto-select best  # gated by auto_select_min_n

# 3. Judge after execution
strata-plan judge .strata-plans/plan-*.md <outcome>

# 4. After ≥5 judgments, recalibrate thresholds from real data
strata-plan recalibrate
```

---

## Install

**Requires [Hermes Agent](https://hermes-agent.nousresearch.com/docs/getting-started/installation) first.**

```bash
git clone https://github.com/itproco0701/hermes-vibe-coding
cd hermes-vibe-coding
bash install.sh
```

`install.sh` now runs an end-to-end smoke test (Step 9b) that samples a plan, runs the judge,
and checks the bridge — so a broken install fails fast at install time, not at first use.

Optional but recommended tools (installed automatically if missing):

```bash
# Python semantic analysis
pip install pyright

# TypeScript dependency graph
npm install -g madge

# Fast file search
brew install ripgrep   # macOS
apt install ripgrep    # Ubuntu/Debian
```

---

## Usage

```bash
# Describe what you want — agent handles the rest
vibe "add retry logic to the API client" -p ~/myproject

# Show plan only, confirm before executing
vibe "refactor auth module to use dependency injection" --plan-only

# Roll back everything to pre-task state
vibe undo

# Check current branch and loop state
vibe status

# Use hermes-strata directly (works outside vibe-coding loop)
strata-plan sample "add OAuth to the login flow" -n 4
strata-plan pick
strata-plan judge .strata-plans/plan-*.md <outcome>
strata-plan report --last 20
strata-plan templates
```

Inside Hermes chat:

```
/vibe-coding "write tests for the payment service"
/vibe-coding "add OpenTelemetry tracing to all API endpoints"
```

---

## File structure

```
hermes-vibe-coding/
├── SKILL.md                          # Main skill (agentskills.io format)
├── README.md
├── install.sh                        # One-shot installer + smoke test
├── .gitignore
├── scripts/
│   ├── vibe                          # CLI entry point
│   └── vibe_loop.py                  # 7-phase agent loop (hermes-strata wired in)
└── skills/
    ├── hermes-strata/                # StraTA-inspired planning sub-skill
    │   ├── SKILL.md
    │   ├── references/
    │   │   ├── pattern.md            # How to apply StraTA at inference time
    │   │   ├── integration.md        # How it slots into vibe_loop phases
    │   │   └── prompts.md            # Drop-in prompt fragments
    │   └── scripts/
    │       ├── strata_plan.py        # CLI: sample / pick / judge / report / templates / rollback
    │       └── strata_plan           # bash wrapper
    ├── lsp-integration.skill.md
    ├── atomic-modify.skill.md
    ├── error-recovery.skill.md
    ├── repo-explorer.skill.md
    ├── git-integration.skill.md
    └── project-memory.skill.md
```

---

## Supported languages

| Language | LSP | Import graph | Test runner |
|----------|-----|-------------|-------------|
| Python | pyright + mypy | AST-based | pytest |
| TypeScript / JS | tsc + eslint | madge | jest / vitest |
| Go | gopls + staticcheck | `go list` | `go test` |
| Rust | rust-analyzer | cargo | `cargo test` |

---

## How it compares to Claude Code

| Feature | Claude Code | This (v2.4) |
|---------|-------------|-------------|
| Repo map | Full auto | Auto (30min cache) |
| LSP diagnostics | Native | pyright / tsc / gopls / rust-analyzer |
| Cross-file atomicity | Native | AST graph + blast radius |
| Self-correction | Built-in | 10-type classifier + strata-judge, max 3 cycles |
| Git integration | Native | Full (stash, branch, commit, PR) |
| Cross-session memory | CLAUDE.md only | Structured JSON + Hermes memory API + strata plan↔outcome pairs |
| Multi-candidate planning | None | **StraTA: sample N → pick → self-judge** |

---

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- `git`
- `python3 >= 3.11`
- `ripgrep` (optional — faster repo mapping)

---

## Changelog

- **v2.5.0** (2026-06-18): `hermes-strata` generalization — CJK intent detection (繁中 / 簡中 / 日本語 / 한국어), project-level config (`.hermes/strata-config.json` / `.vibe-config.json`), non-interactive `--auto-select {first,best,random}`, template system, category-aware threshold + `threshold_overrides`, confidence-aware auto-select gate, `recalibrate` from historical judgments. Additive + opt-in — all v2.4.0 calls still work unchanged.
- **v2.4.0** (2026-06-18): `hermes-strata` hardening — robust step extraction, intent-category threshold, judge→Mistake Journal auto-bridge, end-to-end smoke test in `install.sh`, `report` + `templates` + `rollback` subcommands, intent-weight gating
- **v2.3.0** (2026-06-17): Initial `hermes-strata` integration — StraTA-inspired plan sampling + self-judgment, auto-loaded by Intent Detection, wired into `phase_plan()` and `phase_correct()`
- **v2.2.0** (2026-05-15): Mistake Journal with permanent memory + Intent Detection auto-skill loading + 6 sub-skills
- **v2.0.0** (2026-05-15): 7-phase agent loop with LSP, atomic edits, error classifier, git integration
- **v1.0.0** (2026-05-15): Initial release with Dev↔QA↔Fix loop

---

## License

MIT
