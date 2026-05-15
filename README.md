# Hermes Vibe Coding

Vibe Coding meta-skill for Hermes — implements **Dev↔QA↔Fix** agentic loop for Claude Code/Codex-like experience.

## Features

- 🎯 **Intent-driven**: Describe what you want, not how to do it
- 🔄 **Auto-fix loop**: Dev → QA → Fix → QA → ... until green
- 🧠 **Sub-agent orchestration**: Delegates to specialized skills (backend-architect, frontend-developer, api-tester, etc.)
- 📋 **Kanban tracking**: Every task appears as a card in Hermes Kanban
- 📳 **Telegram notifications**: Real-time progress updates

## Installation

### One-liner (any Hermes agent)

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/itproco0701/hermes-vibe-coding/main/install.sh)"
```

### Manual install

```bash
# 1. Clone
git clone https://github.com/itproco0701/hermes-vibe-coding.git /home/workspace/Skills/vibe-coding

# 2. Run auto-setup
bash /home/workspace/Skills/vibe-coding/install.sh

# 3. Restart Hermes
supervisorctl -c /etc/zo/supervisord-user.conf restart hermes
```

## Usage

### Via Hermes TG
```
/vibe Implement POST /api/v1/users with JWT auth
```

### Via Hermes Chat
```
vibe "Add pagination to GET /api/v1/customers" --project /home/workspace/new-erp
```

### Via CLI
```bash
vibe "Fix the 422 error on order-confirmations" -p /home/workspace/new-erp -r 5
```

## Architecture

```
User Intent
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Dev Agent   │────▶│ QA Agent    │────▶│ Fix Agent   │
│ (implement)│     │ (verify)    │     │ (patch)     │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           ▼                   ▼
                      Pass? ── No ──▶ Loop back
                           │
                          Yes
                           │
                           ▼
                    Task Complete ✅
```

## Requirements

- Hermes agent with `orchestrator_enabled: true`
- Delegation enabled (`max_iterations >= 3`)
- Telegram bot connected (optional, for notifications)

## Files

```
vibe-coding/
├── SKILL.md                        # Skill definition
├── install.sh                      # Auto-setup script
├── README.md                       # This file
├── scripts/
│   ├── vibe_loop.py               # Core Dev↔QA↔Fix loop
│   └── vibe                       # CLI wrapper
└── references/
    ├── hermes-integration.md      # Hermes config details
    ├── context-loading.md          # Context strategy
    └── quickstart.md              # Quick start guide
```

## License

MIT
