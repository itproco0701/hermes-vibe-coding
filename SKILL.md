---
name: vibe-coding
description: Vibe Coding meta-skill for Hermes — implements the Dev↔QA↔Fix agentic loop with permanent Mistake Journal to prevent repeated errors. Achieves Claude Code/Codex-like vibe coding experience.
risk: medium
source: custom
date_added: '2026-05-15'
compatibility: Hermes Agent >= 1.0 (any platform)
metadata:
  author: aipplaw.zo.computer
  version: 2.0.0
  homepage: https://github.com/itproco0701/hermes-vibe-coding
allowed-tools: Bash, Read, Edit, Glob, Grep, WebSearch, WebRead

# Auto-Install
auto_install:
  script: install.sh
  deps:
    - ruamel.yaml
  config_patches:
    - path: skills.external_dirs
      op: add_if_missing
      values:
        - /home/workspace/Skills
        - ~/.hermes/skills/vibe-coding
  verification:
    - "vibe --help"
    - "test -f ~/.hermes/skills/vibe-coding/SKILL.md"

# Portability
portable:
  directory: vibe-coding/
  files:
    - SKILL.md
    - install.sh
    - scripts/vibe
    - scripts/vibe_loop.py
    - references/hermes-integration.md
    - references/context-loading.md
    - references/quickstart.md
    - .vibe-context.example.json
  install_command: |
    mkdir -p ~/.hermes/skills && cp -r vibe-coding ~/.hermes/skills/ && bash ~/.hermes/skills/vibe-coding/install.sh
  remote_install: |
    cd ~ && git clone https://github.com/itproco0701/hermes-vibe-coding.git && bash hermes-vibe-coding/install.sh
---

# Vibe Coding — Hermes Native Integration with Mistake Journal

## What This Skill Does

Wraps Hermes's native capabilities into a **Dev↔QA↔Fix loop** with a **permanent Mistake Journal** that records every thinking confusion or judgment error, and checks them before each step to prevent repeating mistakes.

## Core Loop with Mistake Memory

```
User Intent
  ↓
  ├─ Check Mistake Journal (relevant past errors for this task)
  ↓
Developer Agent ← Inject mistake warnings into prompt
  ↓
  ├─ Check Mistake Journal (before QA)
  ↓
QA Agent ← Inject mistake warnings into prompt
  ↓
  ├─ PASS → Done ✅
  └─ FAIL → Analyze failure → Record as Mistake → Fix → Re-loop
```

**Key difference from v1**: Every step checks the mistake journal first. Every failure is analyzed and recorded permanently. Repeated mistakes are flagged with increasing urgency.

## Mistake Journal

### What Gets Recorded

| Category | Description | Example |
|----------|-------------|---------|
| `confusion` | 思考錯亂 — misunderstood requirements | "Tried to implement GraphQL when API is REST" |
| `misjudgment` | 判斷錯誤 — wrong technical decision | "Used SQLite syntax for PostgreSQL" |
| `repeated_error` | 重複犯錯 — same mistake again | "Forgot to add pagination for the 3rd time" |
| `wrong_assumption` | 錯誤假設 — built on wrong premise | "Assumed field was `sup_id` but it's `supp_id`" |
| `scope_creep` | 範圍蔓延 — modified unrelated code | "Changed auth middleware while fixing sales API" |
| `schema_mismatch` | 結構不匹配 | "Frontend expected `total_amount` but backend returns `total`" |
| `missing_import` | 缺少依賴 | "Forgot to import `Supplier` model in sales router" |

### How It Works

1. **Before Dev step**: `check_mistakes_before_action()` finds relevant past mistakes based on task context, related files, and category
2. **Before QA step**: Same check — QA also looks for known mistake patterns
3. **After QA failure**: `analyze_failure_for_mistake()` auto-categorizes the error and records it
4. **Same mistake repeated**: `occurrence_count` increments, warning urgency increases
5. **Permanent storage**: `.vibe-mistakes.json` in project root, persists across sessions

### Journal File: `.vibe-mistakes.json`

```json
{
  "project": "threeic-erp",
  "created_at": "2026-05-15T10:00:00+08:00",
  "mistakes": [
    {
      "id": "a1b2c3d4e5f6",
      "category": "schema_mismatch",
      "context": "Task: Implement POST /api/v1/sales/order-confirmations, Attempt: 1",
      "mistake": "Schema mismatch: missing required field total_amount",
      "lesson": "Always verify request/response schemas match the model definition",
      "related_files": ["app/api/sales.py", "app/models/sales.py"],
      "timestamp": "2026-05-15T10:30:00+08:00",
      "session_id": "20260515_103000",
      "occurrence_count": 2,
      "last_occurred": "2026-05-15T14:00:00+08:00"
    }
  ]
}
```

## Hermes Capabilities Used

| Capability | How Used |
|------------|----------|
| `delegation` | Spawn developer + QA as child agents |
| `kanban` | Track session progress, retries |
| `state.db` | Persist vibe-context across sessions |
| `checkpoint` | Snapshot after each dev/QA pass |
| `Telegram` | Real-time notifications |
| `skills.external_dirs` | Auto-discover this skill |
| **Mistake Journal** | **Permanent error memory, checked before every step** |

## Usage (Any Hermes Agent)

**Telegram:**
```
/vibe Implement POST /api/users with JWT auth
```

**CLI:**
```bash
# Run vibe coding session
vibe "your task" -p /path/to/project

# View mistake journal
vibe --mistakes -p /path/to/project

# Reset mistake journal
vibe --clean-mistakes -p /path/to/project

# Check session status
vibe --status
```

**Direct Python:**
```bash
python3 scripts/vibe_loop.py "task" --project-path /path
python3 scripts/vibe_loop.py --show-mistakes --project-path /path
python3 scripts/vibe_loop.py --clean-mistakes --project-path /path
```

## Files

```
vibe-coding/
├── SKILL.md                    ← This file
├── install.sh                  ← Auto-configure Hermes
├── README.md                   ← GitHub README
├── .vibe-context.example.json  ← Reference context
├── scripts/
│   ├── vibe                    ← CLI wrapper (supports --mistakes)
│   └── vibe_loop.py            ← Core loop engine with Mistake Journal
└── references/
    ├── hermes-integration.md   ← Deep integration docs
    ├── context-loading.md       ← Context strategy
    └── quickstart.md           ← Quick start guide
```

## Dependencies

- `ruamel.yaml` (Python package)
- Hermes >= 1.0
- Telegram bot (optional, for notifications)

## Exit Criteria

| Outcome | Condition |
|---------|-----------|
| PASS | QA verifies no failures |
| FAIL | Max retries reached |
| ESCALATE | Human input needed |

## Changelog

- **v2.0.0** (2026-05-15): Added permanent Mistake Journal with auto-categorization, pre-step checking, and repeated-error tracking
- **v1.0.0** (2026-05-15): Initial release with Dev↔QA↔Fix loop
