# Vibe Coding Quickstart

## Prerequisites

- Hermes agent running and configured
- Project at `/home/workspace/new-erp` (ThreeIC ERP) or any other project
- Telegram connected (optional, for notifications)

## Installation

The skill is already installed at `/home/workspace/Skills/vibe-coding/`.

For CLI access, add to your PATH:
```bash
export PATH="$PATH:/home/workspace/Skills/vibe-coding/scripts"
# Or symlink
ln -s /home/workspace/Skills/vibe-coding/scripts/vibe /usr/local/bin/vibe
```

## Quick Start

### 1. Check Current Status

```bash
vibe --status
# or
python3 /home/workspace/Skills/vibe-coding/scripts/vibe_loop.py --status
```

### 2. Start a Vibe Session

```bash
# Via CLI wrapper
vibe "Implement user auth endpoint" -p /home/workspace/new-erp

# Via Python directly
python3 /home/workspace/Skills/vibe-coding/scripts/vibe_loop.py \
    "Implement user auth endpoint" \
    --project-path /home/workspace/new-erp \
    --board threeic-erp \
    --max-retries 3
```

### 3. View Results

```bash
# Check kanban
hermes kanban list --board=threeic-erp

# Check vibe context
cat /home/workspace/new-erp/.vibe-context.json | python3 -m json.tool
```

## ThreeIC ERP Examples

### Example 1: Add New API Endpoint

```bash
vibe "Add GET /api/v1/customers endpoint with pagination" \
    -p /home/workspace/new-erp \
    -b threeic-erp
```

### Example 2: Fix Frontend Bug

```bash
vibe "Fix dashboard stats showing NaN when no data" \
    -p /home/workspace/erp-frontend \
    -b threeic-erp
```

### Example 3: Full-Stack Feature

```bash
vibe "Implement customer CRUD with frontend table" \
    -p /home/workspace/new-erp \
    -b threeic-erp \
    -r 5
```

## Via Hermes Chat (Telegram)

```
/vibe Implement POST /api/users endpoint for ThreeIC ERP
```

Or simply describe what you want:
```
幫我新增一個客戶管理頁面，包含搜尋和分頁功能
```

## Understanding the Output

### Vibe Loop Stages

1. **🚀 Started** — Session initialized, kanban task created
2. **👨‍💻 Dev Attempt N** — Developer agent implementing
3. **🔍 QA Verification** — API tester running
4. **✅ PASS** — All tests pass, task done
5. **❌ FAIL** — Tests failed, retrying
6. **🚫 BLOCKED** — Max retries reached, needs human help

### Vibe Context File

The `.vibe-context.json` file tracks the session:

```json
{
  "project": "new-erp",
  "project_path": "/home/workspace/new-erp",
  "created_at": "2026-05-15T03:00:00",
  "history": [
    {
      "attempt": 1,
      "dev_report": "Added GET /api/v1/customers",
      "files_modified": ["app/api/customers.py"],
      "qa_result": "FAIL",
      "qa_failures": [
        {"test": "GET /api/v1/customers", "error": "404 Not Found"}
      ]
    },
    {
      "attempt": 2,
      "dev_report": "Fixed route registration",
      "files_modified": ["app/main.py"],
      "qa_result": "PASS",
      "qa_failures": []
    }
  ]
}
```

## Debugging

### Check Hermes Logs

```bash
tail -f /dev/shm/hermes.log
```

### Check Kanban Directly

```bash
sqlite3 /root/.hermes/kanban.db "
SELECT id, title, status FROM tasks 
WHERE labels LIKE '%vibe-coding%' 
ORDER BY updated_at DESC LIMIT 5;"
```

### Check Checkpoints

```bash
ls -la /root/.hermes/checkpoints/vibe_*
```

## Configuration

### Environment Variables

```bash
export VIBE_MAX_RETRIES=3
export VIBE_DEFAULT_BOARD=threeic-erp
export VIBE_NOTIFY=true
```

### Hermes Config

Ensure delegation is enabled in `/root/.hermes/config.yaml`:

```yaml
delegation:
  enabled: true
  max_iterations: 50
  subagent_auto_approve: false
```

## Next Steps

- Read `SKILL.md` for full workflow details
- Read `references/hermes-integration.md` for Hermes internals
- Read `references/context-loading.md` for context management
