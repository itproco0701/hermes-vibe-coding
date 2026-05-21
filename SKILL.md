---
name: vibe-coding
description: Vibe Coding meta-skill for Hermes — implements the Dev↔QA↔Fix agentic loop with permanent Mistake Journal and Intent Detection auto-skill loading. Achieves Claude Code/Codex-like vibe coding experience.
risk: medium
source: custom
date_added: '2026-05-15'
compatibility: Hermes Agent >= 1.0 (any platform)
metadata:
  author: aipplaw.zo.computer
  version: 2.2.0
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
    - skills/atomic-modify.skill.md
    - skills/error-recovery.skill.md
    - skills/git-integration.skill.md
    - skills/lsp-integration.skill.md
    - skills/project-memory.skill.md
    - skills/repo-explorer.skill.md
  install_command: |
    mkdir -p ~/.hermes/skills && cp -r vibe-coding ~/.hermes/skills/ && bash ~/.hermes/skills/vibe-coding/install.sh
  remote_install: |
    cd ~ && git clone https://github.com/itproco0701/hermes-vibe-coding.git && bash hermes-vibe-coding/install.sh
---

# Vibe Coding — Hermes Native Integration with Mistake Journal

## What This Skill Does

Wraps Hermes's native capabilities into a **Dev↔QA↔Fix loop** with:
1. **Permanent Mistake Journal** — records every thinking confusion or judgment error, checks before each step
2. **Intent Detection** — auto-loads relevant skills based on request keywords
3. **6 Sub-Skills** — repo-explorer, lsp-integration, atomic-modify, error-recovery, git-integration, project-memory

## Intent Detection — Auto-Skill Loading

**When the user says "vibe 幫我XXX" or "/vibe XXX", analyze the request and automatically load the skills that match.** Read the full request before deciding which skills to load — do NOT ask the user, just load them.

### Skill Mapping Table

| Keywords in request | Skills to load |
|---------------------|----------------|
| `ERP` / `OC` / `AR` / `AP` / `GL` / `庫存` / `stock` / `訂單` / `order` / `採購` / `purchase` / `出貨` / `shipment` | `frontend-ui-engineering`, `test-driven-development` |
| `TD` / `TDD` / `測試` / `test` / `pytest` / `jest` | `test-driven-development` |
| `review` / `審查` / `程式碼品質` / `code quality` / `lint` | `requesting-code-review` |
| `重構` / `refactor` / `rename` / `搬移` / `move module` | `atomic-modify`, `lsp-integration` |
| `部署` / `deploy` / `release` / `上線` / `production` | `git-integration`, `project-memory` |
| `debug` / `修復` / `fix` / `修bug` / `error` / `500` / `422` / `404` | `error-recovery`, `lsp-integration` |
| `效能` / `performance` / `優化` / `optimize` / `slow` / `N+1` | `lsp-integration`, `project-memory` |
| `安全` / `security` / `auth` / `JWT` / `RBAC` / `權限` | `requesting-code-review`, `error-recovery` |
| `API` / `endpoint` / `路由` / `route` / `CRUD` | `atomic-modify`, `test-driven-development` |
| `前端` / `frontend` / `UI` / `頁面` / `component` | `frontend-ui-engineering`, `lsp-integration` |
| `後端` / `backend` / `server` / `FastAPI` / `database` | `atomic-modify`, `project-memory` |
| `數據庫` / `DB` / `PostgreSQL` / `migration` / `schema` | `atomic-modify`, `project-memory`, `lsp-integration` |
| `報表` / `report` / `dashboard` / `analytics` / `分析` | `frontend-ui-engineering`, `test-driven-development` |
| `新功能` / `new feature` / `新增` / `implement` | `repo-explorer`, `atomic-modify`, `test-driven-development` |
| `整合` / `integration` / `第三方` / `third-party` / `webhook` | `error-recovery`, `test-driven-development` |
| `文件` / `documentation` / `README` / `API doc` | `project-memory` |
| `記憶` / `memory` / `歷史` / `之前的` / `上次` | `project-memory` |
| `rollback` / `undo` / `復原` / `回滾` | `git-integration` |

### Procedure

1. Scan the user's full request for keywords above
2. Load each matching skill via `skill_view(name)`
3. Follow the loaded skill's workflow IN ADDITION to this vibe-coding loop
4. If no keywords match, proceed with vibe-coding alone
5. If the request mixes multiple domains, load ALL matching skills

### Auto-Skill Loading in vibe_loop.py

The intent detection is implemented in `scripts/vibe_loop.py` via the `detect_skills()` function:

```python
def detect_skills(intent: str) -> list[str]:
    """Scan intent for keywords and return matching skill names."""
    KEYWORD_SKILL_MAP = {
        frozenset(["erp","oc","ar","ap","gl","庫存","stock","訂單","order","採購","purchase","出貨","shipment"]):
            ["frontend-ui-engineering", "test-driven-development"],
        frozenset(["td","tdd","測試","test","pytest","jest"]):
            ["test-driven-development"],
        frozenset(["review","審查","程式碼品質","code quality","lint"]):
            ["requesting-code-review"],
        frozenset(["重構","refactor","rename","搬移","move module"]):
            ["atomic-modify", "lsp-integration"],
        frozenset(["部署","deploy","release","上線","production"]):
            ["git-integration", "project-memory"],
        frozenset(["debug","修復","fix","修bug","error","500","422","404"]):
            ["error-recovery", "lsp-integration"],
        frozenset(["效能","performance","優化","optimize","slow","n+1"]):
            ["lsp-integration", "project-memory"],
        frozenset(["安全","security","auth","jwt","rbac","權限"]):
            ["requesting-code-review", "error-recovery"],
        frozenset(["api","endpoint","路由","route","crud"]):
            ["atomic-modify", "test-driven-development"],
        frozenset(["前端","frontend","ui","頁面","component"]):
            ["frontend-ui-engineering", "lsp-integration"],
        frozenset(["後端","backend","server","fastapi","database"]):
            ["atomic-modify", "project-memory"],
        frozenset(["數據庫","db","postgresql","migration","schema"]):
            ["atomic-modify", "project-memory", "lsp-integration"],
        frozenset(["報表","report","dashboard","analytics","分析"]):
            ["frontend-ui-engineering", "test-driven-development"],
        frozenset(["新功能","new feature","新增","implement"]):
            ["repo-explorer", "atomic-modify", "test-driven-development"],
        frozenset(["整合","integration","第三方","third-party","webhook"]):
            ["error-recovery", "test-driven-development"],
        frozenset(["文件","documentation","readme","api doc"]):
            ["project-memory"],
        frozenset(["記憶","memory","歷史","之前的","上次"]):
            ["project-memory"],
        frozenset(["rollback","undo","復原","回滾"]):
            ["git-integration"],
    }
    intent_lower = intent.lower()
    matched = set()
    for keywords, skills in KEYWORD_SKILL_MAP.items():
        if any(kw in intent_lower for kw in keywords):
            matched.update(skills)
    return sorted(matched)
```

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
