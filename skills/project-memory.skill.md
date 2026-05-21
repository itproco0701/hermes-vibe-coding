---
name: project-memory
description: |
  Cross-session project state persistence for Hermes vibe-coding. Saves repo maps,
  task history, user preferences, known pitfalls, and codebase conventions across
  sessions. This is Hermes's unique advantage over Claude Code — the agent gets
  smarter about your project the more you use it.
version: 1.0.0
metadata:
  hermes:
    tags: [memory, cross-session, project-state, vibe-coding]
    category: software-development
    requires_toolsets: [terminal]
---

# Project Memory Skill

## Why This Matters

Claude Code starts fresh every session. You have to re-explain context every time.
Hermes's memory system means the agent accumulates project knowledge across sessions:
- Remembers the repo structure (doesn't re-explore every time)
- Knows your preferences ("always use async/await", "prefer composition over inheritance")
- Remembers past mistakes ("don't use X library — it caused Y bug last time")
- Tracks unresolved issues from previous sessions

---

## Memory Schema

Each project gets a structured memory entry:

```json
{
  "project_id": "my-api-service",
  "root": "/home/user/projects/my-api-service",
  "stack": {
    "lang": "typescript",
    "framework": "fastify",
    "test_runner": "jest",
    "linter": "eslint",
    "package_manager": "pnpm"
  },
  "conventions": [
    "All async functions use try/catch, never .catch()",
    "Errors extend BaseError class in src/errors.ts",
    "Tests use factory functions from tests/factories/",
    "Config comes from environment via src/config.ts, never hardcoded"
  ],
  "known_pitfalls": [
    "src/db/pool.ts: connection pool has max 10 — don't exceed in tests",
    "The auth middleware caches tokens for 5min — tests may need cache flush",
    "Don't import from index.ts in tests — causes circular dependency"
  ],
  "unresolved": [
    "The retry logic in api-client.ts is brittle under high load — revisit",
    "Test coverage for payment module is < 40% — needs attention"
  ],
  "task_history": [
    {
      "date": "2026-05-10",
      "intent": "Add retry logic to API client",
      "files_changed": ["src/api-client.ts", "tests/api-client.test.ts"],
      "outcome": "success",
      "cycles": 1,
      "commit": "abc1234"
    }
  ],
  "repo_map_cache": "...",
  "last_updated": "2026-05-17T10:30:00Z"
}
```

---

## Save Project State

```bash
memory_save_project() {
  local project_id="$1"   # e.g. "my-api-service"
  local root="${2:-$PWD}"

  local mem_file="$HOME/.hermes/project-memory/${project_id}.json"
  mkdir -p "$(dirname "$mem_file")"

  # Merge with existing memory if it exists
  python3 - "$mem_file" "$project_id" "$root" <<'PYEOF'
import json, sys, os
from datetime import datetime
from pathlib import Path

mem_file = sys.argv[1]
project_id = sys.argv[2]
root = sys.argv[3]

# Load existing or start fresh
if Path(mem_file).exists():
    with open(mem_file) as f:
        mem = json.load(f)
else:
    mem = {"project_id": project_id, "root": root, "conventions": [],
           "known_pitfalls": [], "unresolved": [], "task_history": []}

mem["last_updated"] = datetime.utcnow().isoformat() + "Z"
mem["root"] = root

with open(mem_file, "w") as f:
    json.dump(mem, f, indent=2)

print(f"Memory saved: {mem_file}")
PYEOF

  # Also save to Hermes native memory system
  hermes memory save \
    --key "project:$project_id" \
    --file "$mem_file" \
    --tags "project-memory,$project_id" \
    2>/dev/null || echo "(Hermes memory API not available — saved to file only)"
}
```

---

## Load Project State

```bash
memory_load_project() {
  local project_id="$1"
  local mem_file="$HOME/.hermes/project-memory/${project_id}.json"

  # Try Hermes native memory first
  local mem
  mem=$(hermes memory get --key "project:$project_id" 2>/dev/null)

  if [[ -z "$mem" ]] && [[ -f "$mem_file" ]]; then
    mem=$(cat "$mem_file")
  fi

  if [[ -z "$mem" ]]; then
    echo "No memory found for project: $project_id"
    echo "This appears to be a new project. Running initial exploration..."
    return 1
  fi

  # Output as context for Hermes
  echo "=== Project Memory: $project_id ==="
  echo "$mem" | python3 -c "
import json, sys
m = json.load(sys.stdin)
print(f\"Root: {m.get('root')}\")
print(f\"Stack: {m.get('stack', {})}\")
print(f\"Last updated: {m.get('last_updated')}\")
print()
convs = m.get('conventions', [])
if convs:
    print('Conventions (follow these):')
    for c in convs: print(f'  • {c}')
pitfalls = m.get('known_pitfalls', [])
if pitfalls:
    print()
    print('Known pitfalls (avoid these):')
    for p in pitfalls: print(f'  ⚠️  {p}')
unresolved = m.get('unresolved', [])
if unresolved:
    print()
    print('Unresolved issues (be aware):')
    for u in unresolved: print(f'  🔶 {u}')
history = m.get('task_history', [])[-5:]
if history:
    print()
    print('Recent task history:')
    for t in reversed(history):
        print(f\"  {t['date']}: {t['intent']} → {t['outcome']}\")
"
}
```

---

## Record Task Completion

```bash
memory_record_task() {
  local project_id="$1"
  local intent="$2"
  local files_changed=("${@:3}")

  local mem_file="$HOME/.hermes/project-memory/${project_id}.json"

  python3 - "$mem_file" "$intent" "${files_changed[@]}" <<'PYEOF'
import json, sys
from datetime import datetime
from pathlib import Path

mem_file = sys.argv[1]
intent = sys.argv[2]
files = sys.argv[3:]

if not Path(mem_file).exists():
    print("No memory file — skipping task recording")
    sys.exit(0)

with open(mem_file) as f:
    mem = json.load(f)

entry = {
    "date": datetime.utcnow().strftime("%Y-%m-%d"),
    "intent": intent,
    "files_changed": files,
    "outcome": "success",
    "timestamp": datetime.utcnow().isoformat() + "Z"
}

mem.setdefault("task_history", []).append(entry)
# Keep last 50 tasks
mem["task_history"] = mem["task_history"][-50:]
mem["last_updated"] = datetime.utcnow().isoformat() + "Z"

with open(mem_file, "w") as f:
    json.dump(mem, f, indent=2)

print(f"Task recorded: {intent}")
PYEOF
}
```

---

## Learn Convention from Task

After a successful task, extract conventions to remember:

```bash
memory_learn_convention() {
  local project_id="$1"
  local new_convention="$2"
  local mem_file="$HOME/.hermes/project-memory/${project_id}.json"

  python3 - "$mem_file" "$new_convention" <<'PYEOF'
import json, sys
from pathlib import Path

mem_file = sys.argv[1]
convention = sys.argv[2]

if not Path(mem_file).exists():
    print("No memory file")
    sys.exit(0)

with open(mem_file) as f:
    mem = json.load(f)

convs = mem.setdefault("conventions", [])
if convention not in convs:
    convs.append(convention)
    with open(mem_file, "w") as f:
        json.dump(mem, f, indent=2)
    print(f"Convention learned: {convention}")
else:
    print("Convention already known.")
PYEOF
}
```

---

## Integration with vibe-coding

Add these calls to `vibe_loop.py`:

```python
# At session start — before Phase 1
project_id = os.path.basename(project_root)
memory_loaded = memory_load_project(project_id)
if not memory_loaded:
    run_repo_explorer(project_root)  # first-time exploration

# At end of Phase 7 (report)
memory_record_task(project_id, intent, *modified_files)

# After a successful task — prompt Hermes to extract conventions
# "Based on this task, what conventions should be remembered?"
```

---

## Memory CLI

```bash
# List all projects with saved memory
hermes-memory list-projects() {
  ls "$HOME/.hermes/project-memory/"*.json 2>/dev/null \
    | xargs -I{} python3 -c "
import json, sys
with open('{}') as f: m = json.load(f)
print(m['project_id'], '|', m.get('last_updated','?')[:10],
      '|', len(m.get('task_history',[])), 'tasks')
"
}

# Show memory for a project
# vibe-memory show <project-id>

# Add a convention manually
# vibe-memory learn <project-id> "Always use pnpm, not npm"

# Add a known pitfall
# vibe-memory pitfall <project-id> "Don't import from barrel files in tests"

# Clear memory for a project
# vibe-memory clear <project-id>
```
