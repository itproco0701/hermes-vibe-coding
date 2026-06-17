#!/bin/bash
# =============================================================================
# Vibe Coding Skill v2 — Install Script
# Closes the gap with Claude Code across 6 core dimensions
# =============================================================================

set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_NAME="vibe-coding"
REQUIRED_PYTHON="3.11"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "\n${BOLD}${CYAN}── $1 ──${NC}"; }

echo ""
echo -e "${BOLD}=============================================="
echo -e "  Vibe Coding Skill v2"
echo -e "  Claude Code-parity agent loop for Hermes"
echo -e "==============================================${NC}"
echo ""

# ─────────────────────────────────────────────
# Step 1: Verify Hermes
# ─────────────────────────────────────────────
section "Step 1: Verify Hermes"
HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"
CONFIG_FILE="$HERMES_DIR/config.yaml"

if [[ ! -f "$CONFIG_FILE" ]]; then
    error "Hermes config not found at $CONFIG_FILE"
    error "Install Hermes first:"
    echo "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    exit 1
fi
info "Hermes config found: $CONFIG_FILE"

# ─────────────────────────────────────────────
# Step 2: Python version check
# ─────────────────────────────────────────────
section "Step 2: Python version"
if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install Python 3.11+."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; print('ok' if sys.version_info >= (3,11) else 'old')")
if [[ "$PY_OK" == "old" ]]; then
    warn "Python $PY_VER detected. Python 3.11+ recommended (tomllib required)."
    warn "Continuing — some repo-explorer features may be limited."
else
    info "Python $PY_VER ✓"
fi

# ─────────────────────────────────────────────
# Step 3: Python dependencies
# ─────────────────────────────────────────────
section "Step 3: Python dependencies"

pip_install() {
    local pkg="$1"
    python3 -c "import ${pkg//-/_}" 2>/dev/null && { info "$pkg already installed ✓"; return; }
    pip install "$pkg" --quiet --break-system-packages 2>/dev/null \
    || pip install "$pkg" --quiet 2>/dev/null \
    || warn "Could not install $pkg — some features may be limited"
    info "Installed: $pkg"
}

pip_install "ruamel.yaml"

# Optional but recommended
if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    read -r -p "Install pyright for Python LSP diagnostics? [Y/n] " ans
    if [[ ! "$ans" =~ ^[Nn]$ ]]; then
        pip install pyright --quiet --break-system-packages 2>/dev/null \
        || pip install pyright --quiet 2>/dev/null \
        || warn "pyright install failed — Python LSP will fall back to syntax-only"
        info "pyright installed ✓"
    fi
fi

# ─────────────────────────────────────────────
# Step 4: Optional system tools
# ─────────────────────────────────────────────
section "Step 4: Optional tools"

check_tool() {
    local cmd="$1" label="$2" hint="$3"
    if command -v "$cmd" &>/dev/null; then
        info "$label ✓ ($(command -v $cmd))"
    else
        warn "$label not found — $hint"
    fi
}

check_tool "rg"          "ripgrep"    "install: brew install ripgrep / apt install ripgrep"
check_tool "git"         "git"        "required — please install git"
check_tool "gh"          "GitHub CLI" "optional for PR creation: https://cli.github.com"
check_tool "madge"       "madge"      "optional for TS import graphs: npm install -g madge"
check_tool "staticcheck" "staticcheck" "optional for Go: go install honnef.co/go/tools/cmd/staticcheck@latest"

# Warn if git is missing (it's actually required)
if ! command -v git &>/dev/null; then
    error "git is required. Please install git before continuing."
    exit 1
fi

# ─────────────────────────────────────────────
# Step 5: Register all skill directories in Hermes config
# ─────────────────────────────────────────────
section "Step 5: Register skill directories"

python3 - <<PYEOF
import sys
from pathlib import Path
try:
    from ruamel.yaml import YAML
except ImportError:
    print("SKIP: ruamel not available — add skills manually to $CONFIG_FILE")
    sys.exit(0)

config_file = Path("$CONFIG_FILE")
yaml = YAML()
yaml.preserve_quotes = True
config = yaml.load(config_file.read_text())

if 'skills' not in config:
    config['skills'] = {}
if 'external_dirs' not in config['skills']:
    config['skills']['external_dirs'] = []

external_dirs = config['skills']['external_dirs']
skill_dir = Path("$SKILL_DIR").resolve()

# Register both the root (for SKILL.md) and the skills/ subdir
dirs_to_add = [str(skill_dir), str(skill_dir / "skills")]

added = []
existing = [str(Path(d).resolve()) for d in external_dirs]
for d in dirs_to_add:
    if d not in existing:
        external_dirs.append(d)
        added.append(d)

config['skills']['external_dirs'] = external_dirs

import io
buf = io.StringIO()
yaml.dump(config, buf)
config_file.write_text(buf.getvalue())

if added:
    for a in added:
        print(f"  Registered: {a}")
else:
    print("  All skill directories already registered ✓")
PYEOF

# ─────────────────────────────────────────────
# Step 6: Make scripts executable
# ─────────────────────────────────────────────
section "Step 6: Script permissions"

chmod +x "$SKILL_DIR/scripts/vibe"
chmod +x "$SKILL_DIR/scripts/vibe_loop.py"
info "scripts/vibe ✓"
info "scripts/vibe_loop.py ✓"

# ─────────────────────────────────────────────
# Step 7: Create CLI symlinks
# ─────────────────────────────────────────────
section "Step 7: CLI symlinks"

link_or_path() {
    local src="$1" dest="$2" name="$3"
    if ln -sf "$src" "$dest" 2>/dev/null; then
        info "Linked: $dest → $src"
    else
        warn "Could not write to /usr/local/bin (no sudo). Adding to PATH instead."
        for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            [[ -f "$rc" ]] && grep -q "$SKILL_DIR/scripts" "$rc" 2>/dev/null && continue
            echo "export PATH=\"$SKILL_DIR/scripts:\$PATH\"" >> "$rc" 2>/dev/null && \
                info "Added to $rc"
        done
        warn "Restart your shell or run: export PATH=\"$SKILL_DIR/scripts:\$PATH\""
    fi
}

link_or_path "$SKILL_DIR/scripts/vibe"         "/usr/local/bin/vibe"         "vibe"
link_or_path "$SKILL_DIR/scripts/vibe_loop.py" "/usr/local/bin/vibe_loop.py" "vibe_loop.py"
link_or_path "$SKILL_DIR/skills/hermes-strata/scripts/strata-plan" "/usr/local/bin/strata-plan" "strata-plan"

# ─────────────────────────────────────────────
# Step 8: Create memory directory
# ─────────────────────────────────────────────
section "Step 8: Memory directory"

MEMORY_DIR="$HOME/.hermes/project-memory"
mkdir -p "$MEMORY_DIR"
info "Project memory directory: $MEMORY_DIR ✓"

# ─────────────────────────────────────────────
# Step 9: Verify all skill files
# ─────────────────────────────────────────────
section "Step 9: Verify skill files"

REQUIRED_FILES=(
    "SKILL.md"
    "scripts/vibe"
    "scripts/vibe_loop.py"
    "skills/lsp-integration.skill.md"
    "skills/atomic-modify.skill.md"
    "skills/error-recovery.skill.md"
    "skills/repo-explorer.skill.md"
    "skills/git-integration.skill.md"
    "skills/project-memory.skill.md"
    "skills/hermes-strata/SKILL.md"
    "skills/hermes-strata/scripts/strata-plan"
)

ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$SKILL_DIR/$f" ]]; then
        info "$f ✓"
    else
        error "$f MISSING"
        ALL_OK=false
    fi
done

if [[ "$ALL_OK" == false ]]; then
    error "Some skill files are missing. Re-clone the repo and try again."
    exit 1
fi

# ─────────────────────────────────────────────
# Step 10: Check Hermes skill discovery
# ─────────────────────────────────────────────
section "Step 10: Hermes skill discovery"

if command -v hermes &>/dev/null; then
    if hermes skills list 2>/dev/null | grep -q "vibe-coding"; then
        info "Hermes can see vibe-coding ✓"
    else
        warn "Hermes doesn't see the skill yet — restart Hermes after install"
    fi
else
    warn "hermes not in PATH — ensure Hermes is installed"
fi

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✅ Installation complete!${NC}"
echo ""
echo "Usage:"
echo "  vibe \"add retry logic to API client\" -p ~/myproject"
echo "  vibe \"refactor auth module\" --plan-only"
echo "  vibe undo"
echo ""
echo "Inside Hermes:"
echo "  /vibe-coding \"write tests for the payment service\""
echo ""
echo "Restart Hermes to activate the new skills:"
echo "  hermes restart"
echo ""
