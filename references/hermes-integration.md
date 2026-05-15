# Hermes Integration Reference

## Overview

This document details how the vibe-coding skill integrates with Hermes's core systems.

## Hermes Components Used

### 1. Delegation System

The `config.yaml` delegation settings control how sub-agents are spawned:

```yaml
delegation:
  model: ''                    # Uses default provider (MiniMax M2.7)
  provider: ''                 # Let Hermes choose
  max_iterations: 50           # Enough for full vibe loop
  max_concurrent_children: 3   # Developer + QA can run together
  subagent_auto_approve: false # Human must approve final changes
  default_toolsets:
    - terminal                 # Run test scripts
    - file                     # Read/write code
    - web                      # API health checks
```

### 2. Kanban Board

Hermes's SQLite kanban tracks each vibe session as a task:

```sql
-- Tables used by vibe-coding
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,         -- Task description
  board TEXT DEFAULT 'default',-- Project board
  status TEXT DEFAULT 'pending',-- pending/in_progress/done/blocked
  created_at TEXT,
  updated_at TEXT,
  labels TEXT                   -- 'vibe-coding'
);

CREATE TABLE task_events (
  id INTEGER PRIMARY KEY,
  task_id INTEGER,
  event_type TEXT,             -- 'vibe_attempt'
  description TEXT,
  created_at TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### 3. Checkpoints

Hermes checkpoint mechanism stores session snapshots:

```
/root/.hermes/checkpoints/
├── vibe_Implement_USER_attempt1_20260515_103000.json
├── vibe_Implement_USER_attempt2_20260515_103015.json
└── ...
```

### 4. State Database

Hermes `state.db` stores conversation context and can be queried:

```sql
-- Check Hermes conversation state
SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 5;

-- Check session tokens
SELECT * FROM session_tokens WHERE expires_at > datetime('now');
```

### 5. Toolsets

The toolsets available to vibe-coding sub-agents:

| Toolset | Capabilities |
|---------|-------------|
| `hermes-cli` | Execute hermes commands, kanban ops |
| `terminal` | Run bash commands, test scripts |
| `file` | Read/write workspace files |
| `web` | HTTP requests for API testing |

## Hermes CLI Commands for Vibe Coding

```bash
# Start a vibe session via CLI
hermes exec --skill=vibe-coding "Implement user auth endpoint"

# Check kanban board
hermes kanban list --board=threeic-erp

# View task details
hermes kanban view <task_id>

# Force-complete a blocked task
hermes kanban done <task_id>

# View checkpoint history
hermes checkpoint list --filter=vibe

# Restart with fresh state
hermes session reset
```

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Vibe Coding Skill                            │
│                                                                  │
│  Python vibe_loop.py                                             │
│  ├── load_vibe_context()  → reads .vibe-context.json           │
│  ├── create_kanban_task() → writes to kanban.db                 │
│  ├── spawn_developer_agent() → Hermes delegation API           │
│  ├── spawn_qa_agent()     → agency-api-tester sub-agent       │
│  ├── create_checkpoint()   → writes to checkpoints/             │
│  └── notify_telegram()     → writes to state.db notifications  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Hermes Core                                  │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ Delegation  │  │   Kanban    │  │ Checkpoint  │             │
│  │   Engine    │  │   (SQLite)  │  │  Manager    │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Toolsets   │  │   State     │  │ Telegram    │             │
│  │  (file/term │  │    DB       │  │  Bridge     │             │
│  │   /web/cl)  │  │ (SQLite)    │  │             │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Sub-Agents (Skills)                           │
│                                                                  │
│  agency-backend-architect  → FastAPI/PostgreSQL design          │
│  agency-frontend-developer → React/Vite implementation          │
│  agency-api-tester         → Endpoint verification              │
│  engineering-devops-automator → Scripts & automation           │
│  engineering-code-reviewer → Final quality gate                 │
└─────────────────────────────────────────────────────────────────┘
```

## Environment Variables

The vibe-coding skill reads these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_HOME` | `/root/.hermes` | Hermes root directory |
| `HERMES_KANBAN_DB` | `$HERMES_HOME/kanban.db` | Kanban database path |
| `HERMES_STATE_DB` | `$HERMES_HOME/state.db` | State database path |
| `VIBE_MAX_RETRIES` | `3` | Default max fix attempts |
| `VIBE_DEFAULT_BOARD` | `default` | Default kanban board |
| `VIBE_NOTIFY` | `true` | Enable Telegram notifications |

## Error Handling

### Hermes Not Running
```python
if not os.path.exists(KANBAN_DB):
    print("[ERROR] Hermes kanban not found. Is Hermes running?")
    sys.exit(1)
```

### Database Locked
```python
try:
    conn = sqlite3.connect(KANBAN_DB, timeout=5)
except sqlite3.OperationalError:
    print("[WARN] Kanban DB locked, waiting...")
    time.sleep(1)
    conn = sqlite3.connect(KANBAN_DB, timeout=10)
```

### Checkpoint Failure
```python
try:
    create_checkpoint(...)
except Exception as e:
    print(f"[WARN] Checkpoint failed: {e}")
    # Continue anyway - checkpoints are best-effort
```

## Testing the Integration

```bash
# Test kanban connectivity
python3 -c "
import sqlite3
conn = sqlite3.connect('/root/.hermes/kanban.db')
print(conn.execute('SELECT COUNT(*) FROM tasks').fetchone())
"

# Test vibe loop (dry run)
python3 /home/workspace/Skills/vibe-coding/scripts/vibe_loop.py \
    "Test task" \
    --project-path /home/workspace/new-erp \
    --no-notify

# Check checkpoints
ls -la /root/.hermes/checkpoints/vibe_*
```
