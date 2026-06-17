# Pattern — StraTA for inference, not training

StraTA is an RL framework, but three of its ideas transfer cleanly to
**inference-time agent design** without any training:

| StraTA training trick | What it does | How to use it at inference |
|---|---|---|
| **Hierarchical strategy → action** | Sample a high-level plan first, then condition every action on it | Before writing code, write the plan in plain language; condition every subsequent edit on that plan |
| **Diverse strategy sampling** | Sample N trajectories, pick the best | Sample N=2–3 candidate approaches for a non-trivial task, let the user pick |
| **Critical self-judgment** | Model scores its own plan↔outcome alignment | After Verify, run `strata-plan judge <plan> <outcome>` and feed the score back into the next cycle |

The fourth trick — **stepwise advantage / GRPO grouping** — is purely a
training-time signal and does **not** apply at inference.

## Why this is useful

A typical agent "thinks linearly": intent → plan → execute → done. That
fails on non-trivial tasks because the agent commits to the first
plausible plan and then defends it through corrections. StraTA-style
thinking adds two cheap checks:

1. **Before plan** — is there a simpler plan we're missing?
2. **After verify** — did the outcome actually address the plan, or did
   we just paper over the failure?

Both checks cost one extra LLM call and one CLI run. They prevent the
two most common vibe-coding failure modes (premature commitment and
false PASS).

## How it slots into the vibe-coding loop

```
Phase 0  Git checkpoint          (unchanged)
Phase 1  Repo map                (unchanged)
Phase 2  Plan                    ★ StraTA sample N=3 candidate plans
                                 ★ User picks one (or auto-pick highest)
Phase 3  Execute                 (unchanged)
Phase 4  Verify                  (unchanged)
Phase 5  Self-correction         ★ StraTA judge plan↔outcome before re-loop
Phase 6  Commit                  (unchanged)
Phase 7  Report                  (unchanged)
```

The CLI is at `scripts/strata_plan.py`; both Phase 2 and Phase 5
reference it. See `references/integration.md` for the exact edits
to apply to `vibe-coding/scripts/vibe_loop.py`.

## When to enable it

Default off. Enable when the intent matches any of:

- "plan", "architect", "設計", "架構", "approach"
- "compare", "選方案", "哪個好", "best of", "option"
- "refactor", "rewrite", "重構", "重寫" (multiple viable shapes)
- "fix", "debug", "修復" (after first verify fails, before re-try)

For trivial changes (one-line bug fix, single-file rename), the
sampling overhead is not worth it — stay linear.
