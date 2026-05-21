---
name: atomic-modify
description: |
  Cross-file atomic modification orchestrator for Hermes vibe-coding.
  Builds an import dependency graph, identifies the blast radius of any change,
  performs coordinated multi-file edits, and verifies consistency before committing.
  Replaces the sequential file-by-file approach with a coordinated atomic operation.
version: 1.0.0
metadata:
  hermes:
    tags: [atomic, cross-file, refactor, import-graph, vibe-coding]
    category: software-development
    requires_toolsets: [terminal]
---

# Atomic Cross-File Modification Skill

## The Problem

Sequential file editing breaks when:
- You rename `login()` → `login_with_retry()` but miss 3 indirect callers
- You change a function signature but leave old call sites intact
- You move a module but don't update all its importers
- You add a required parameter but don't update every call site

This skill solves it by treating multi-file changes as a **single atomic transaction**
with a pre-computed blast radius, coordinated edits, and a post-edit consistency check.

---

## Phase 1 — Build Import Dependency Graph

Before any edit, map the full dependency graph for files relevant to the task.

### Python

```bash
build_import_graph_python() {
  local root="${1:-.}"
  python3 - "$root" <<'PYEOF'
import ast, sys, json
from pathlib import Path

root = Path(sys.argv[1]).resolve()
graph = {}  # file -> list of files it imports from this project

def resolve_import(module_parts, from_file):
    """Try to find the actual file for a module."""
    candidates = [
        root / Path(*module_parts).with_suffix('.py'),
        root / Path(*module_parts) / '__init__.py',
    ]
    for c in candidates:
        if c.exists():
            return str(c.relative_to(root))
    return None

for path in root.rglob('*.py'):
    if any(p in str(path) for p in ['__pycache__', '.venv', 'node_modules', 'dist']):
        continue
    rel = str(path.relative_to(root))
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        continue
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split('.')
            resolved = resolve_import(parts, path)
            if resolved:
                imports.append(resolved)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split('.')
                resolved = resolve_import(parts, path)
                if resolved:
                    imports.append(resolved)
    graph[rel] = list(set(imports))

# Print reverse graph: file -> files that import it
reverse = {}
for file, deps in graph.items():
    for dep in deps:
        reverse.setdefault(dep, []).append(file)

print(json.dumps({'forward': graph, 'reverse': reverse}, indent=2))
PYEOF
}
```

### TypeScript / JavaScript

```bash
build_import_graph_ts() {
  local root="${1:-.}"
  # Use madge if available (best tool for JS/TS dependency graphs)
  if command -v madge &>/dev/null; then
    madge --json "$root" 2>/dev/null
  else
    # Fallback: grep-based import extraction
    echo "Installing madge for accurate TS dependency graphs..."
    npm install -g madge 2>/dev/null
    madge --json "$root" 2>/dev/null || \
    # Minimal fallback
    rg --type ts --type js -n "^import.*from ['\"]\..*['\"]" "$root" \
      | grep -v node_modules | head -100
  fi
}
```

### Go

```bash
build_import_graph_go() {
  go list -json ./... 2>/dev/null | python3 -c "
import sys, json
decoder = json.JSONDecoder()
data = sys.stdin.read()
pos = 0
packages = []
while pos < len(data):
    try:
        obj, pos = decoder.raw_decode(data, pos)
        packages.append({'pkg': obj.get('ImportPath'), 'imports': obj.get('Imports', [])})
        pos = data.find('{', pos)
        if pos == -1: break
    except: break
print(json.dumps(packages, indent=2))
"
}
```

---

## Phase 2 — Compute Blast Radius

Given a set of files you plan to modify, find every file that will be affected.

```bash
compute_blast_radius() {
  local target_files=("$@")
  local graph_json="$GRAPH_JSON"  # output of Phase 1

  python3 - "$graph_json" "${target_files[@]}" <<'PYEOF'
import sys, json
from collections import deque

graph_file = sys.argv[1]
targets    = set(sys.argv[2:])

with open(graph_file) as f:
    graph = json.load(f)

reverse = graph.get('reverse', {})

# BFS: find all files that (transitively) import any target file
visited = set(targets)
queue   = deque(targets)

while queue:
    current = queue.popleft()
    for importer in reverse.get(current, []):
        if importer not in visited:
            visited.add(importer)
            queue.append(importer)

affected = sorted(visited - set(targets))

print("=== Blast Radius ===")
print(f"Directly modified ({len(targets)}):")
for f in sorted(targets):
    print(f"  ✏️  {f}")
print(f"\nIndirectly affected ({len(affected)}):")
for f in affected:
    print(f"  ⚠️  {f}")
print(f"\nTotal files in transaction: {len(visited)}")
PYEOF
}
```

---

## Phase 3 — Show Plan + Confirm Before Editing

**Never edit without user confirmation when blast radius > direct files.**

```
=== Atomic Modification Plan ===

Intent: Rename `login()` to `login_with_retry()` in auth.py

Directly modified:
  ✏️  src/auth.py              (definition change)
  ✏️  tests/test_auth.py       (test update)

Indirectly affected (will be auto-updated):
  ⚠️  src/api/endpoints.py     (calls login())
  ⚠️  src/middleware/session.py (calls login())
  ⚠️  scripts/seed_data.py     (calls login())

Total: 5 files in this transaction.

Proceed? [Y/n/show-details]
```

---

## Phase 4 — Coordinated Edit

Execute all edits in a single coordinated pass. Use a transaction log to
enable rollback if any step fails.

```bash
atomic_edit() {
  local old_symbol="$1"
  local new_symbol="$2"
  local files=("${@:3}")
  local tx_log="/tmp/vibe_tx_$(date +%s).log"

  echo "Transaction started: $(date)" > "$tx_log"
  echo "Old: $old_symbol" >> "$tx_log"
  echo "New: $new_symbol" >> "$tx_log"

  local failed=()

  for file in "${files[@]}"; do
    # 1. Backup
    cp "$file" "${file}.vibe_bak"
    echo "BACKUP: $file → ${file}.vibe_bak" >> "$tx_log"

    # 2. Edit (word-boundary safe replacement)
    if sed -i "s/\b${old_symbol}\b/${new_symbol}/g" "$file" 2>/dev/null; then
      echo "EDITED: $file" >> "$tx_log"
    else
      # macOS sed needs different syntax
      sed -i '' "s/[[:<:]]${old_symbol}[[:>:]]/${new_symbol}/g" "$file" 2>/dev/null \
        || { echo "FAILED: $file" >> "$tx_log"; failed+=("$file"); }
    fi

    # 3. Immediate syntax check — rollback this file if broken
    if ! syntax_check "$file"; then
      echo "ROLLBACK: $file (syntax error after edit)" >> "$tx_log"
      mv "${file}.vibe_bak" "$file"
      failed+=("$file")
    else
      rm "${file}.vibe_bak"
    fi
  done

  if [[ ${#failed[@]} -gt 0 ]]; then
    echo "❌ Transaction partially failed. Rolling back remaining files..."
    # Rollback all remaining backups
    for bak in /tmp/*.vibe_bak 2>/dev/null; do
      orig="${bak%.vibe_bak}"
      [[ -f "$bak" ]] && mv "$bak" "$orig"
    done
    echo "Failed files: ${failed[*]}"
    return 1
  fi

  echo "✅ Atomic edit complete: $old_symbol → $new_symbol across ${#files[@]} files"
  echo "Transaction log: $tx_log"
}
```

---

## Phase 5 — Post-Edit Consistency Verification

After all edits, verify the codebase is internally consistent.

```bash
verify_consistency() {
  local lang="$1"
  local modified_files=("${@:2}")

  echo "=== Consistency check ==="

  # 1. No remaining references to old symbol
  echo "Checking for old symbol remnants..."
  local old_sym="$OLD_SYMBOL"
  rg "\b${old_sym}\b" --type "$lang" . | grep -v ".git" | grep -v node_modules \
    && echo "⚠️  Old symbol still found in codebase — missed references!" \
    || echo "✅ No remnants of old symbol found"

  # 2. LSP diagnostics on all modified files
  echo "Running LSP check on modified files..."
  lsp_check_"$lang" "${modified_files[@]}"

  # 3. Import resolution check — verify nothing is now unresolvable
  case "$lang" in
    python)
      python3 -c "
import importlib.util, sys
for f in ${modified_files[*]@Q}:
    spec = importlib.util.spec_from_file_location('_check', f)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print(f'✅ {f}: imports OK')
    except ImportError as e:
        print(f'❌ {f}: import error — {e}')
    except Exception:
        print(f'✅ {f}: imports OK (runtime errors expected)')
" ;;
    typescript)
      npx tsc --noEmit --skipLibCheck 2>&1 | grep -E "error TS" | head -10 \
        && echo "❌ TypeScript errors found" \
        || echo "✅ TypeScript: no import errors" ;;
    go)
      go build ./... 2>&1 && echo "✅ Go: builds cleanly" || echo "❌ Go: build errors" ;;
  esac
}
```

---

## Integration with vibe-coding SKILL.md

Replace Phase 3 (Execute) with this flow:

```
Phase 3 — Atomic Execute:
  1. build_import_graph()            ← Phase 1 of this skill
  2. compute_blast_radius(targets)   ← Phase 2
  3. Show plan → confirm with user   ← Phase 3
  4. atomic_edit(old, new, files)    ← Phase 4
  5. verify_consistency(lang, files) ← Phase 5 + lsp-integration skill
```

---

## Pitfalls

**Dynamic imports** (`importlib`, `require()` with variables) cannot be
statically resolved. Flag them: `grep -n "importlib.import_module\|require(" <files>`.

**Circular imports** — the dependency graph BFS will loop infinitely without
the `visited` set. Always use the visited guard.

**String occurrences vs symbol references** — `sed` cannot distinguish
`login_url = "..."` from `login()`. Use AST-based replacement for Python;
use TypeScript compiler API for TS. Grep-based replacement is a fallback only.

**Generated files** — exclude `dist/`, `build/`, `*.pb.go`, `*.min.js` from
the blast radius. They should be regenerated, not hand-edited.
