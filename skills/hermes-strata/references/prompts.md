# Prompts — what to actually say to the LLM

`hermes-strata` ships with no LLM call. The CLI is a deterministic
artifact store. The LLM does the reasoning. Here are the two prompts
to use.

## 1. Plan sampling prompt (Phase 2)

Use this when `strata-plan sample` has produced a bundle and you want
the LLM to flesh out each card's "Files to modify" and "Definition of
done" sections:

```text
You are a planning agent. You will be given 3 high-level strategy cards
for the same intent. For EACH card:

1. Read the existing repo map (symbols, test locations, recent commits).
2. Write a concrete "Files to modify" table (File | Change type | Reason).
3. Write a concrete "Files NOT to touch" list.
4. Write testable "Definition of done" checkboxes.

Output the 3 expanded plans as three fenced markdown blocks labeled
PLAN_MINIMAL, PLAN_STRUCTURED, PLAN_REWRITE. Do not write code. Do not
defend one over another — present the tradeoffs honestly.

Intent:
{intent}

Repo map:
{repo_map}

Strategy cards (from strata-plan):
{cards_json}
```

## 2. Plan↔outcome judgment prompt (Phase 5)

Use this when `strata-plan judge` has returned `score < 0.6` and you
need the LLM to explain the gap and propose a different strategy:

```text
You are the same model that produced the plan, reviewing its outcome.
The deterministic judge scored {score}/1.0 because {reason}.

Plan: {plan_path}
Outcome: {outcome}
Missed steps: {missed}

Answer in 3 sections:
1. WHY — which step of the plan did the outcome fail to address, and
   why? Cite the actual test output / error.
2. WHICH STRATEGY — among the other strategy cards (minimal /
   structured / rewrite), would have anticipated this failure? Justify.
3. NEXT STEP — one concrete edit the executor should make before the
   next verify cycle. Reference file paths and line numbers if known.
```

The first prompt produces a richer plan; the second produces a
targeted correction. Both rely on the artifacts written by
`strata-plan sample` and `strata-plan judge` — no human-in-the-loop
required at runtime.
