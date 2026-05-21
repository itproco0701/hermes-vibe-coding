---
name: repo-explorer
description: |
  Automatic project root detection and repo-map builder for Hermes vibe-coding.
  Detects language, framework, entry points, test locations, and config files
  without requiring -p path from the user. Produces a structured repo-map that
  feeds directly into the vibe-coding planning phase.
version: 1.0.0
metadata:
  hermes:
    tags: [repo-map, project-detection, context, vibe-coding]
    category: software-development
    requires_toolsets: [terminal]
---

# Repo Explorer Skill

## Purpose

Claude Code's most powerful invisible feature is that it *already knows* your
codebase before you say anything. This skill replicates that by running a
structured exploration at session start and caching the result in Hermes memory.

---

## Phase 1 — Find Project Root

```bash
find_project_root() {
  local start="${1:-$PWD}"
  local current="$start"

  # Walk up until we find a project root marker
  ROOT_MARKERS=(
    "package.json" "pyproject.toml" "Cargo.toml" "go.mod"
    "composer.json" ".git" "Makefile" "CMakeLists.txt"
    "pom.xml" "build.gradle" "mix.exs" "pubspec.yaml"
  )

  while [[ "$current" != "/" ]]; do
    for marker in "${ROOT_MARKERS[@]}"; do
      if [[ -e "$current/$marker" ]]; then
        echo "$current"
        return 0
      fi
    done
    current="$(dirname "$current")"
  done

  # Fallback: use git root
  git rev-parse --show-toplevel 2>/dev/null || echo "$start"
}

PROJECT_ROOT=$(find_project_root)
echo "Project root detected: $PROJECT_ROOT"
cd "$PROJECT_ROOT"
```

---

## Phase 2 — Detect Language & Framework

```bash
detect_stack() {
  local root="${1:-.}"
  declare -A stack

  # Language detection
  [[ -f "$root/package.json" ]]    && stack[lang]="javascript"
  [[ -f "$root/tsconfig.json" ]]   && stack[lang]="typescript"
  [[ -f "$root/pyproject.toml" ]]  && stack[lang]="python"
  [[ -f "$root/setup.py" ]]        && stack[lang]="python"
  [[ -f "$root/Cargo.toml" ]]      && stack[lang]="rust"
  [[ -f "$root/go.mod" ]]          && stack[lang]="go"
  [[ -f "$root/pom.xml" ]]         && stack[lang]="java"
  [[ -f "$root/composer.json" ]]   && stack[lang]="php"

  # Framework detection
  if [[ "${stack[lang]}" == "typescript" || "${stack[lang]}" == "javascript" ]]; then
    local deps
    deps=$(python3 -c "import json; d=json.load(open('$root/package.json')); print(json.dumps({**d.get('dependencies',{}), **d.get('devDependencies',{})}))" 2>/dev/null)
    echo "$deps" | grep -q '"next"'    && stack[framework]="nextjs"
    echo "$deps" | grep -q '"react"'   && stack[framework]="${stack[framework]:-react}"
    echo "$deps" | grep -q '"express"' && stack[framework]="${stack[framework]:-express}"
    echo "$deps" | grep -q '"fastify"' && stack[framework]="${stack[framework]:-fastify}"
    echo "$deps" | grep -q '"jest"'    && stack[test_runner]="jest"
    echo "$deps" | grep -q '"vitest"'  && stack[test_runner]="vitest"
  fi

  if [[ "${stack[lang]}" == "python" ]]; then
    local deps
    deps=$(cat "$root/pyproject.toml" "$root/requirements.txt" 2>/dev/null)
    echo "$deps" | grep -qi "fastapi"  && stack[framework]="fastapi"
    echo "$deps" | grep -qi "django"   && stack[framework]="${stack[framework]:-django}"
    echo "$deps" | grep -qi "flask"    && stack[framework]="${stack[framework]:-flask}"
    stack[test_runner]="pytest"
  fi

  # Output
  echo "Language:   ${stack[lang]:-unknown}"
  echo "Framework:  ${stack[framework]:-none detected}"
  echo "Test runner:${stack[test_runner]:-unknown}"
}
```

---

## Phase 3 — Build Symbol Map

```bash
build_symbol_map() {
  local root="${1:-.}"
  local lang="${2:-python}"
  local output_file="${3:-/tmp/repo_symbol_map.txt}"

  echo "=== Symbol Map ===" > "$output_file"

  case "$lang" in
    python)
      python3 - "$root" >> "$output_file" <<'PYEOF'
import ast, sys
from pathlib import Path

root = Path(sys.argv[1])
for path in sorted(root.rglob('*.py')):
    if any(p in str(path) for p in ['__pycache__', '.venv', 'dist', 'build']):
        continue
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        continue
    rel = path.relative_to(root)
    symbols = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            symbols.append(f"  def {node.name}({', '.join(args)})  [line {node.lineno}]")
        elif isinstance(node, ast.ClassDef):
            symbols.append(f"  class {node.name}  [line {node.lineno}]")
    if symbols:
        print(f"\n{rel}:")
        print('\n'.join(symbols[:20]))  # cap at 20 per file
PYEOF
      ;;

    typescript|javascript)
      # Extract exports, functions, classes, interfaces
      rg --type ts --type js \
        "^(export\s+)?(async\s+)?function\s+\w+|^(export\s+)?class\s+\w+|^export\s+(const|type|interface)\s+\w+" \
        "$root" --no-heading -n | grep -v node_modules | head -120 >> "$output_file"
      ;;

    go)
      rg --type go "^func\s+|^type\s+\w+\s+(struct|interface)" \
        "$root" --no-heading -n | head -80 >> "$output_file"
      ;;

    rust)
      rg --type rust "^pub\s+(fn|struct|enum|trait|impl)\s+\w+|^fn\s+\w+" \
        "$root" --no-heading -n | head -80 >> "$output_file"
      ;;
  esac

  wc -l "$output_file" | awk '{print "Symbol map: "$1" lines"}'
  echo "$output_file"
}
```

---

## Phase 4 — Entry Point & Config Map

```bash
map_entry_points() {
  local root="${1:-.}"
  local lang="$2"

  echo "=== Entry Points ==="

  case "$lang" in
    python)
      # main modules
      find "$root" -name "main.py" -o -name "app.py" -o -name "run.py" \
        -o -name "manage.py" -o -name "wsgi.py" -o -name "asgi.py" \
        | grep -v __pycache__ | head -10
      # pyproject.toml scripts
      python3 -c "
import tomllib
try:
    with open('$root/pyproject.toml', 'rb') as f:
        d = tomllib.load(f)
    scripts = d.get('tool', {}).get('poetry', {}).get('scripts', \
              d.get('project', {}).get('scripts', {}))
    for k, v in scripts.items():
        print(f'  script: {k} → {v}')
except: pass
" 2>/dev/null
      ;;

    typescript|javascript)
      python3 -c "
import json
with open('$root/package.json') as f:
    d = json.load(f)
print('main:', d.get('main', 'not set'))
print('scripts:')
for k, v in d.get('scripts', {}).items():
    print(f'  {k}: {v}')
" 2>/dev/null
      ;;

    go)
      find "$root" -name "main.go" | grep -v vendor | head -5
      ;;

    rust)
      grep -A2 "\[\[bin\]\]" "$root/Cargo.toml" 2>/dev/null || echo "src/main.rs"
      ;;
  esac

  echo ""
  echo "=== Config Files ==="
  find "$root" -maxdepth 2 \( \
    -name "*.env" -o -name ".env*" -o -name "config.yaml" \
    -o -name "config.toml" -o -name "settings.py" \
    -o -name "appsettings.json" -o -name "config.json" \
  \) | grep -v node_modules | grep -v __pycache__ | head -10
}
```

---

## Phase 5 — Test Location Map

```bash
map_tests() {
  local root="${1:-.}"
  local lang="$2"

  echo "=== Test Files ==="

  case "$lang" in
    python)
      find "$root" \( -name "test_*.py" -o -name "*_test.py" \) \
        | grep -v __pycache__ | grep -v .venv | sort | head -20

      # Coverage report if available
      if [[ -f "$root/.coverage" ]] || [[ -f "$root/coverage.xml" ]]; then
        echo ""
        echo "=== Coverage (last run) ==="
        python -m coverage report --skip-empty 2>/dev/null | tail -5
      fi
      ;;

    typescript|javascript)
      find "$root" \( -name "*.test.ts" -o -name "*.spec.ts" \
        -o -name "*.test.js" -o -name "*.spec.js" \) \
        | grep -v node_modules | sort | head -20
      ;;

    go)
      find "$root" -name "*_test.go" | grep -v vendor | head -20
      ;;

    rust)
      grep -rn "#\[cfg(test)\]\|#\[test\]" "$root/src" 2>/dev/null | head -20
      ;;
  esac
}
```

---

## Phase 6 — Save Repo Map to Hermes Memory

```bash
save_repo_map() {
  local root="$1"
  local map_file="/tmp/repo_map_$(basename $root).md"

  cat > "$map_file" <<MAPEOF
# Repo Map: $(basename $root)
Generated: $(date)
Root: $root

## Stack
$(detect_stack "$root")

## Entry Points
$(map_entry_points "$root" "$LANG")

## Symbol Map
$(cat "$SYMBOL_MAP_FILE")

## Tests
$(map_tests "$root" "$LANG")

## Recent Changes
$(git log --oneline -10 2>/dev/null || echo "No git history")
MAPEOF

  echo "Repo map saved: $map_file"

  # Save to Hermes persistent memory
  hermes memory save \
    --key "repo_map:$(basename $root)" \
    --value "$(cat $map_file)" \
    --tags "repo-map,$(basename $root)" \
    2>/dev/null && echo "Saved to Hermes memory" || echo "Hermes memory save skipped"

  echo "$map_file"
}
```

---

## Full Explore Command

```bash
# One-shot: explore current directory and produce repo map
explore() {
  local root
  root=$(find_project_root "${1:-$PWD}")
  cd "$root"

  detect_stack "$root"
  SYMBOL_MAP_FILE=$(build_symbol_map "$root" "$LANG")
  map_entry_points "$root" "$LANG"
  map_tests "$root" "$LANG"
  save_repo_map "$root"

  echo ""
  echo "✅ Repo map complete. Ready for vibe coding."
}
```

---

## Caching Strategy

Re-exploring on every task is slow for large repos. Use this cache policy:

```bash
should_refresh_map() {
  local root="$1"
  local cache_file="/tmp/repo_map_$(basename $root).md"

  # Refresh if:
  # 1. Cache doesn't exist
  [[ ! -f "$cache_file" ]] && return 0

  # 2. Cache is older than 30 minutes
  local age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || stat -f %m "$cache_file") ))
  [[ $age -gt 1800 ]] && return 0

  # 3. Any source file changed since cache was built
  local newest_src
  newest_src=$(find "$root" -name "*.py" -o -name "*.ts" -o -name "*.go" \
    | grep -v node_modules | xargs ls -t 2>/dev/null | head -1)
  [[ "$newest_src" -nt "$cache_file" ]] && return 0

  # Cache is fresh
  return 1
}
```
