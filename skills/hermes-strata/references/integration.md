# Integration — patching vibe-coding's loop

`hermes-strata` is designed to be auto-loaded by
`vibe-coding/scripts/vibe_loop.py` whenever the intent matches one of
the trigger keywords. There are two integration points.

## 1. Auto-load (already done in this repo)

`vibe-coding/scripts/vibe_loop.py` already has a `KEYWORD_SKILL_MAP`.
The patch is a 7-line append:

```python
KEYWORD_SKILL_MAP.update({
    frozenset(["plan","architect","設計","架構","approach","refactor","rewrite","重構","重寫","compare","選方案","哪個好","option"]):
        ["hermes-strata", "atomic-modify"],
    frozenset(["fix","debug","修復","修bug","error","500","422","404"]):
        ["hermes-strata", "error-recovery", "lsp-integration"],
})
```

## 2. Phase 2 hook — sample plans before commit

In `phase_plan()`, before `confirm = input(...)`, insert:

```python
from pathlib import Path
import subprocess
stra = Path(__file__).parent / "hermes-strata" / "scripts" / "strata_plan.py"
if stra.exists():
    intent_lower = intent.lower()
    triggers = ("plan","architect","設計","架構","refactor","rewrite","重構","重寫","compare","選方案")
    if any(k in intent_lower for k in triggers):
        print("[hermes-strata] sampling candidate plans…")
        subprocess.run([sys.executable, str(stra), "sample", intent, "-n", "3"], check=False)
        bp = sorted(Path(".strata-plans").glob("bundle-*.json"))[-1]
        subprocess.run([sys.executable, str(stra), "pick", bp.name], check=False)
        plan = Path(sorted(Path(".strata-plans").glob(f"plan-*-{Path(bp).stem.split('-',1)[1].replace('bundle-','')}.md"))[-1]).read_text()
        plan_file.write_text(plan)
        print(f"Plan (selected by StraTA): {plan_file}")
```

(In production you would inline this as a function; the snippet above
shows the shape.)

## 3. Phase 5 hook — judge plan↔outcome before re-loop

In `phase_correct()`, after the fix attempt but before returning, add:

```python
plan_files = sorted(Path(".strata-plans").glob("plan-*.md"))
if plan_files:
    last_plan = plan_files[-1]
    outcome = test_result or error_output or "(no output captured)"
    subprocess.run(
        [sys.executable, str(stra), "judge", str(last_plan), outcome, "--score-hint", str(0.7)],
        check=False,
    )
```

The judgment is logged to `.strata-plans/judgments.jsonl` and printed.
If `score < 0.6`, the agent should treat the fix as incomplete and
either escalate or extend the loop with a different strategy card.

## When NOT to inject

- One-line typo fix
- Pure rename / move (no logic change)
- Tasks where the user has already specified the exact approach

In those cases the heuristic in `references/pattern.md` applies: stay
linear, do not sample.

## Verifying the integration

```bash
strata-plan sample "Add JWT to POST /api/users" -n 3
echo "1" | strata-plan pick
strata-plan judge .strata-plans/plan-*.md "401 returned; tests pass"
strata-plan status
```

Expected:

- `sample` writes `.strata-plans/bundle-<ts>.json`
- `pick` writes `.strata-plans/plan-<ts>-<tag>.md`
- `judge` writes `.strata-plans/judgments.jsonl` and prints `score: ≥0.6`
- `status` shows counts and the last judgment's `next_action`
