---
name: vibe-coding
description: Vibe Coding meta-skill for Hermes — implements the Dev↔QA↔Fix agentic loop to achieve Claude Code/Codex-like vibe coding experience. Use when the user wants to implement a feature or fix by describing intent, and the system handles execution, verification, and iterative fixing automatically.
risk: medium
source: custom
date_added: '2026-05-15'
compatibility: Hermes Agent >= 1.0 (any platform)
metadata:
  author: aipplaw.zo.computer
  version: 1.0.0
  homepage: https://github.com/zocomputer/skills/tree/main/vibe-coding
allowed-tools: Bash, Read, Edit, Glob, Grep, WebSearch, WebRead

# Auto-Install
auto_install:
  script: install.sh          # Run this on target Hermes
  deps:
    - ruamel.yaml             # Python package
  
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
  
  # One-liner install (run on target Hermes)
  install_command: |
    mkdir -p ~/.hermes/skills && cp -r vibe-coding ~/.hermes/skills/ && bash ~/.hermes/skills/vibe-coding/install.sh
  
  # For remote install via curl
  remote_install: |
    cd ~ && curl -fsSL https://zo.pub/aipplaw/vibe-coding/vibe-coding.tar.gz | tar -xz && bash ~/.hermes/skills/vibe-coding/install.sh
---

# Vibe Coding — Hermes Native Integration

## What This Skill Does

Wraps Hermes's native capabilities (delegation, kanban, checkpoints, Telegram) into a Dev↔QA↔Fix loop that mirrors Claude Code/Codex's vibe coding model.

## Core Loop

```
User Intent → Developer → QA → [FAIL? → Fix → Re-QA] → Done
```

All orchestrated via Hermes's existing infrastructure — no new daemons, no external services.

## Hermes Capabilities Used

| Capability | How Used |
|------------|----------|
| `delegation` | Spawn developer + QA as child agents |
| `kanban` | Track session progress, retries |
| `state.db` | Persist vibe-context across sessions |
| `checkpoint` | Snapshot after each dev/QA pass |
| `Telegram` | Real-time notifications |
| `skills.external_dirs` | Auto-discover this skill |

## Auto-Install Feature

This SKILL.md includes `auto_install` metadata so Hermes can automatically:

1. Copy the skill directory to `~/.hermes/skills/vibe-coding/`
2. Run `install.sh` to patch `config.yaml`
3. Create `/usr/local/bin/vibe` symlinks
4. Verify the installation

## Usage (Any Hermes Agent)

**Telegram:**
```
/vibe Implement POST /api/users with JWT auth
```

**CLI:**
```bash
vibe "your task" -p /path/to/project
```

**Kanban:**
```bash
hermes kanban add "your task" --skill=vibe-coding
```

**Direct:**
```bash
python3 ~/.hermes/skills/vibe-coding/scripts/vibe_loop.py "task" --project-path /path
```

## Files

```
vibe-coding/
├── SKILL.md                    ← This file (auto-install manifest)
├── install.sh                  ← Auto-configure Hermes
├── .vibe-context.example.json  ← Reference context
├── scripts/
│   ├── vibe                    ← CLI wrapper
│   └── vibe_loop.py            ← Core loop engine
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