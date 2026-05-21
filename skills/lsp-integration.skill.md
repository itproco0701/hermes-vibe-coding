---
name: lsp-integration
description: |
  LSP-level semantic analysis for Hermes vibe-coding. Replaces pure grep/find
  with type-aware diagnostics: symbol resolution, go-to-definition, find-all-references,
  unused imports, type errors, and missing parameters. Called by vibe-coding
  before and after every code change.
version: 1.0.0
metadata:
  hermes:
    tags: [lsp, semantic, diagnostics, vibe-coding]
    category: software-development
    requires_toolsets: [terminal]
---

# LSP Integration Skill

## Purpose

Pure text search (grep/ripgrep) cannot answer:
- "Is this symbol used anywhere?"
- "What type does this function return?"
- "Did I break any references after renaming?"
- "Are there type errors in the files I just modified?"

This skill wires up language-specific LSP tooling to answer those questions
before committing any change.

---

## Language → LSP Tool Matrix

| Language | LSP Tool | Install |
|----------|----------|---------|
| Python | `pyright` or `pylsp` | `pip install pyright` |
| TypeScript/JS | `typescript-language-server` | `npm i -g typescript-language-server typescript` |
| Go | `gopls` | `go install golang.org/x/tools/gopls@latest` |
| Rust | `rust-analyzer` | `rustup component add rust-analyzer` |
| Ruby | `solargraph` | `gem install solargraph` |

---

## Phase A — Detect Available LSP

```bash
detect_lsp() {
  local lang="$1"
  case "$lang" in
    python)
      command -v pyright   && echo "pyright"   && return
      command -v pylsp     && echo "pylsp"      && return
      command -v mypy      && echo "mypy"       && return
      echo "none" ;;
    typescript|javascript)
      command -v typescript-language-server && echo "tsls" && return
      command -v npx && npx --yes tsc --version &>/dev/null && echo "tsc" && return
      echo "none" ;;
    go)
      command -v gopls     && echo "gopls"      && return
      command -v go        && echo "go-vet"     && return
      echo "none" ;;
    rust)
      command -v rust-analyzer && echo "rust-analyzer" && return
      command -v cargo         && echo "cargo-check"   && return
      echo "none" ;;
    *)
      echo "none" ;;
  esac
}
```

---

## Phase B — Run Diagnostics on Modified Files

### Python (pyright — fastest, no daemon needed)

```bash
lsp_check_python() {
  local files=("$@")

  echo "=== Pyright diagnostics ==="
  pyright "${files[@]}" --outputjson 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
diags = data.get('generalDiagnostics', [])
errors   = [d for d in diags if d['severity'] == 'error']
warnings = [d for d in diags if d['severity'] == 'warning']
print(f'Errors: {len(errors)}, Warnings: {len(warnings)}')
for e in errors:
    f = e['file'].split('/')[-1]
    print(f\"  ERROR {f}:{e['range']['start']['line']+1} — {e['message']}\")
for w in warnings[:5]:
    f = w['file'].split('/')[-1]
    print(f\"  WARN  {f}:{w['range']['start']['line']+1} — {w['message']}\")
sys.exit(0 if not errors else 1)
" || return 1

  # Also run mypy for runtime type checking
  if command -v mypy &>/dev/null; then
    echo "=== Mypy type check ==="
    mypy "${files[@]}" --ignore-missing-imports --no-error-summary 2>&1 | head -20
  fi
}
```

### TypeScript (tsc — full project type check)

```bash
lsp_check_typescript() {
  echo "=== TypeScript type check ==="
  npx tsc --noEmit --skipLibCheck 2>&1 | head -30
  local exit_code=$?

  # Also check unused imports/vars
  echo "=== ESLint semantic rules ==="
  npx eslint . --rule '{"@typescript-eslint/no-unused-vars": "error"}' \
    --ext .ts,.tsx --max-warnings 0 2>&1 | head -20

  return $exit_code
}
```

### Go

```bash
lsp_check_go() {
  echo "=== Go vet ==="
  go vet ./... 2>&1

  echo "=== Staticcheck ==="
  if command -v staticcheck &>/dev/null; then
    staticcheck ./... 2>&1 | head -20
  fi

  # Unused variables and imports are compile errors in Go — build catches them
  echo "=== Build check ==="
  go build ./... 2>&1
}
```

### Rust

```bash
lsp_check_rust() {
  echo "=== Cargo check ==="
  cargo check 2>&1 | tail -30

  echo "=== Clippy (lint) ==="
  cargo clippy -- -D warnings 2>&1 | tail -20
}
```

---

## Phase C — Find All References (before renaming/deleting)

Before renaming a symbol, find every reference to avoid broken imports.

```bash
find_all_references() {
  local symbol="$1"
  local lang="$2"
  local project_root="${3:-.}"

  echo "=== References to '$symbol' ==="

  case "$lang" in
    python)
      # Use ast to find actual references (not string occurrences)
      python3 - "$symbol" "$project_root" <<'PYEOF'
import ast, sys, os
from pathlib import Path

symbol = sys.argv[1]
root   = sys.argv[2]

class RefFinder(ast.NodeVisitor):
    def __init__(self):
        self.refs = []
    def visit_Name(self, node):
        if node.id == symbol:
            self.refs.append(node.lineno)
        self.generic_visit(node)
    def visit_Attribute(self, node):
        if node.attr == symbol:
            self.refs.append(node.lineno)
        self.generic_visit(node)

for path in Path(root).rglob("*.py"):
    if any(p in str(path) for p in ['__pycache__', '.venv', 'node_modules']):
        continue
    try:
        tree = ast.parse(path.read_text())
        finder = RefFinder()
        finder.visit(tree)
        for lineno in finder.refs:
            print(f"{path}:{lineno}")
    except SyntaxError:
        pass
PYEOF
      ;;

    typescript|javascript)
      # ripgrep with word boundary
      rg --type ts --type js -n "\b${symbol}\b" "$project_root" \
        | grep -v node_modules | grep -v ".d.ts" | head -50
      ;;

    go)
      rg -n "\b${symbol}\b" --type go "$project_root" | head -50
      ;;

    rust)
      rg -n "\b${symbol}\b" --type rust "$project_root" | head -50
      ;;
  esac
}
```

---

## Phase D — Unused Symbol Detection

```bash
find_unused_symbols() {
  local lang="$1"

  case "$lang" in
    python)
      if command -v vulture &>/dev/null; then
        echo "=== Unused code (vulture) ==="
        vulture . --min-confidence 80 2>&1 | head -20
      else
        echo "Install vulture for unused symbol detection: pip install vulture"
      fi
      ;;
    typescript)
      npx ts-prune 2>&1 | head -20
      ;;
    go)
      # unused variables = compile error; unused packages flagged by vet
      go vet ./... 2>&1
      ;;
  esac
}
```

---

## Integration with vibe-coding

Call this skill from `vibe_loop.py` at two points:

1. **Before Phase 3 (Execute):** Establish LSP baseline — record existing errors
   so you can distinguish pre-existing issues from regressions.

2. **After Phase 3 (each file write):** Run `lsp_check_<lang>` on modified files.
   If new errors appear that weren't in baseline → trigger correction loop immediately
   rather than waiting for full test suite.

```python
# vibe_loop.py integration point
baseline_errors = run_lsp_check(lang, all_files)
# ... make changes ...
post_change_errors = run_lsp_check(lang, modified_files)
new_errors = post_change_errors - baseline_errors
if new_errors:
    trigger_correction(new_errors)
```

---

## Fallback (no LSP available)

If no LSP tool is detected, fall back gracefully:

```bash
echo "⚠️  No LSP tool found for $LANG."
echo "    Falling back to syntax-only checks."
echo "    For full semantic analysis, install:"
case "$LANG" in
  python)     echo "    pip install pyright" ;;
  typescript) echo "    npm i -g typescript-language-server typescript" ;;
  go)         echo "    go install golang.org/x/tools/gopls@latest" ;;
  rust)       echo "    rustup component add rust-analyzer" ;;
esac

# Minimal fallback: syntax check only
python3 -m py_compile "$FILE" 2>&1   # python
npx tsc --noEmit 2>&1               # typescript
go build ./... 2>&1                  # go
cargo check 2>&1                     # rust
```
