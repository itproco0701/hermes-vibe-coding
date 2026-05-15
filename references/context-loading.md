# Context Loading Strategy

## Overview

Vibe coding quality depends heavily on having the right context at the right time. This document describes how context is loaded, prioritized, and injected into the vibe loop.

## Context Loading Order

When a vibe session starts, context is loaded in this order (highest priority last):

```
1. Vibe Context (.vibe-context.json)     ← Persistent across sessions
2. Project Metadata (package.json, etc.)   ← Dependency & script info
3. AGENTS.md / SOUL.md                     ← Project-specific rules
4. Status Files (THREEIC_STATUS.md, etc.) ← Current development state
5. Task History (vibe loop history)        ← Previous attempts & failures
6. Hermes Memory (session context)         ← Current conversation state
```

## Context Files by Project Type

### Node.js / React Project

```
project/
├── package.json              # dependencies, scripts, name
├── vite.config.ts            # build config
├── tsconfig.json              # TypeScript config
├── src/
│   ├── pages/                 # page components
│   ├── components/            # shared components
│   └── api/                   # API client
├── AGENTS.md                  # project rules (if exists)
├── .vibe-context.json         # vibe session state
└── THREEIC_STATUS.md          # status tracking (if ERP)
```

### Python / FastAPI Project

```
project/
├── pyproject.toml             # project metadata
├── app/
│   ├── main.py                # FastAPI app
│   ├── api/                   # route modules
│   ├── models/                # Pydantic/SQLAlchemy models
│   └── core/                  # config, security
├── alembic/                   # migrations
├── tests/                     # test suite
├── AGENTS.md
├── .vibe-context.json
└── THREEIC_STATUS.md
```

### Python / Django Project

```
project/
├── manage.py
├── project_name/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── users/
│   ├── products/
│   └── orders/
├── AGENTS.md
└── .vibe-context.json
```

## Context Injection into Developer Agent

The developer agent prompt is constructed with these context blocks:

```python
def build_dev_prompt(task: str, project_path: str, ctx: dict) -> str:
    """Build a developer agent prompt with full context."""

    # 1. Task description
    task_block = f"TASK: {task}"

    # 2. Project type and structure
    project_block = load_project_structure(project_path)

    # 3. Previous failures (if retry)
    if ctx.get("last_qa_failures"):
        failures_block = "PREVIOUS FAILURES TO FIX:\n"
        for f in ctx["last_qa_failures"]:
            failures_block += f"  - [{f['test']}] {f['error']}\n"
    else:
        failures_block = ""

    # 4. Project rules from AGENTS.md
    agents_md = load_agents_md(project_path)

    # 5. Current status from STATUS.md
    status_md = load_status_md(project_path)

    return f"""
{task_block}

{failures_block}

## Project Context

{project_block}

## Project Rules (AGENTS.md)

{agents_md}

## Current Status (STATUS.md)

{status_md}

## Instructions

1. Read the relevant source files
2. Make minimal changes to address the task
3. If PREVIOUS FAILURES exist, address each one specifically
4. Write changes to disk
5. Report files_modified and dev_report
"""
```

## Context Priority Rules

### Rule 1: Task Beats Everything
If a task explicitly contradicts a rule in AGENTS.md, the task wins.
- Exception: Security rules always take precedence

### Rule 2: Failures Inject Priority
If QA reported failures, they become the #1 context priority.
```python
if ctx.get("last_qa_failures"):
    prompt += "\n🚨 FIX THESE FAILURES FIRST:\n"
    for f in ctx["last_qa_failures"]:
        prompt += f"- {f['test']}: {f['error']}\n"
```

### Rule 3: Project Structure is Load-Bearing
Always include the directory tree so the agent knows where to write files.

### Rule 4: Preserve Error Messages
Always include the raw error output from QA, don't summarize.
```python
# Bad
"API returned 500 error"

# Good
"POST /api/users returned 500 Internal Server Error
Response body: {\"detail\": \"Unique constraint failed: email\"}
Stack trace: app/api/users.py:45 in create_user
  raise UniqueViolationError from e"
```

## Context Size Limits

Hermes has token limits. Context is trimmed in this order:

1. **Vibe history** → Keep last 3 attempts only
2. **AGENTS.md** → Full content (project rules are sacred)
3. **THREEIC_STATUS.md** → Last 20 lines
4. **Error traces** → Last 500 chars

## Per-Project Context Loading

For the ThreeIC ERP specifically:

```python
THREEIC_CONTEXT_FILES = [
    "/home/workspace/THREEIC_STATUS.md",      # Dev state
    "/home/workspace/AGENTS.md",              # Dev rules
    "/home/workspace/ERP_Test_Plan.md",       # Test coverage
    "/home/workspace/Glory_Metal_SPEC.md",    # Feature spec
]

def load_threeic_context(project_path: str) -> dict:
    ctx = {}
    for f in THREEIC_CONTEXT_FILES:
        if os.path.exists(f):
            ctx[os.path.basename(f)] = read_file(f)
    return ctx
```
