#!/bin/bash
# =============================================================================
# Vibe Coding Skill — Auto-Install Script
# =============================================================================
# This script auto-configures Hermes to recognize and use the vibe-coding skill.
# Run once on any Hermes agent to enable vibe coding.
#
# What it does:
#   1. Verifies Hermes config location
#   2. Adds skills/external_dirs if not present
#   3. Installs required Python dependencies (ruamel.yaml)
#   4. Creates vibe-coding convenience symlinks in /usr/local/bin
#   5. Validates Hermes can see the skill
# =============================================================================

set -e

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_NAME="vibe-coding"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "=============================================="
echo "  Vibe Coding Skill — Auto-Install"
echo "=============================================="
echo ""

# -----------------------------------------------------------------------------
# Step 1: Verify Hermes installation
# -----------------------------------------------------------------------------
info "Checking Hermes installation..."

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes}"
CONFIG_FILE="$HERMES_DIR/config.yaml"

if [[ ! -f "$CONFIG_FILE" ]]; then
    error "Hermes config not found at $CONFIG_FILE"
    error "Is Hermes installed?"
    exit 1
fi
info "Found Hermes config at $CONFIG_FILE"

# -----------------------------------------------------------------------------
# Step 2: Install Python dependencies
# -----------------------------------------------------------------------------
info "Installing Python dependencies..."

if ! python3 -c "import ruamel" 2>/dev/null; then
    warn "Installing ruamel.yaml..."
    pip install ruamel.yaml --quiet
    info "ruamel.yaml installed"
else
    info "ruamel.yaml already installed"
fi

# -----------------------------------------------------------------------------
# Step 3: Update Hermes config — add external_dirs
# -----------------------------------------------------------------------------
info "Updating Hermes config..."

PYTHON_SCRIPT=$(python3 << 'PYEOF'
import sys
from pathlib import Path
from ruamel.yaml import YAML

config_file = Path("$CONFIG_FILE")
yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

content = config_file.read_text()
config = yaml.load(content)

# Ensure skills section exists
if 'skills' not in config:
    config['skills'] = {}

# Ensure external_dirs is a list
if 'external_dirs' not in config['skills']:
    config['skills']['external_dirs'] = []

external_dirs = config['skills']['external_dirs']

# Normalize to list of strings
if isinstance(external_dirs, str):
    external_dirs = [external_dirs]
    config['skills']['external_dirs'] = external_dirs

# Add our paths if not present
skill_dir = "$SKILL_DIR"
paths_to_add = [
    "/home/workspace/Skills",
    "$SKILL_DIR"
]

added = []
for p in paths_to_add:
    # Resolve path
    resolved = str(Path(p).resolve())
    if resolved not in external_dirs:
        external_dirs.append(resolved)
        added.append(resolved)

config['skills']['external_dirs'] = external_dirs

# Write back
config_file.write_text(yaml.dump(config))

if added:
    print("ADDED:" + ",".join(added))
else:
    print("ADDED:none")
PYEOF
)

IFS=',' read -ra ADDED <<< "$PYTHON_SCRIPT"
for path in "${ADDED[@]}"; do
    if [[ "$path" != "ADDED:none" && "$path" != "" ]]; then
        info "Added to external_dirs: $path"
    fi
done
if [[ "$PYTHON_SCRIPT" == "ADDED:none" ]]; then
    info "external_dirs already configured"
fi

# -----------------------------------------------------------------------------
# Step 4: Create convenience symlinks
# -----------------------------------------------------------------------------
info "Creating convenience symlinks..."

# vibe CLI
if [[ ! -L /usr/local/bin/vibe ]]; then
    ln -sf "$SKILL_DIR/scripts/vibe" /usr/local/bin/vibe
    chmod +x /usr/local/bin/vibe
    info "Created /usr/local/bin/vibe"
else
    info "/usr/local/bin/vibe already exists"
fi

# vibe_loop.py
if [[ ! -L /usr/local/bin/vibe_loop.py ]]; then
    ln -sf "$SKILL_DIR/scripts/vibe_loop.py" /usr/local/bin/vibe_loop.py
    info "Created /usr/local/bin/vibe_loop.py"
else
    info "/usr/local/bin/vibe_loop.py already exists"
fi

# -----------------------------------------------------------------------------
# Step 5: Verify installation
# -----------------------------------------------------------------------------
info "Verifying installation..."

# Check skill directory is accessible
if [[ -f "$SKILL_DIR/SKILL.md" ]]; then
    info "SKILL.md found"
else
    error "SKILL.md not found at $SKILL_DIR"
    exit 1
fi

# Check vibe CLI
if /usr/local/bin/vibe --help >/dev/null 2>&1; then
    info "vibe CLI working"
else
    warn "vibe CLI may need Hermes running for full functionality"
fi

# -----------------------------------------------------------------------------
# Step 6: Check if Hermes restart is needed
# -----------------------------------------------------------------------------
echo ""
info "Installation complete!"
echo ""
echo "To activate:"
echo "  1. Restart Hermes:  bash /home/workspace/restart-hermes.sh"
echo "  2. Or via Telegram: /vibe help"
echo ""
echo "To use vibe coding:"
echo "  vibe \"your task\" -p /path/to/project"
echo ""
