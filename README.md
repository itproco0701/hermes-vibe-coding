# hermes-vibe-coding

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill suite for vibe coding —
describe what you want in natural language, and the agent handles repo mapping, planning,
execution, cross-file coordination, self-correction, and git checkpointing.

**v2** closes the gap with [Claude Code](https://claude.ai/code) across all 6 core dimensions,
while leveraging Hermes's unique cross-session memory advantage.

---

## What's new in v2

| Dimension | v1 | v2 |
|-----------|----|----|
| Repo understanding | Manual `-p` path only | Auto root detection + symbol map + 30min cache |
| Semantic analysis | Pure grep/find | LSP diagnostics (pyright, tsc, gopls, rust-analyzer) |
| Cross-file edits | Sequential, no tracking | AST import graph + blast radius + atomic transaction |
| Error self-correction | Generic retry | 10-type classifier + strategy-matched fix agent |
| Feedback loop | Basic stdout capture | Test + lint + LSP + independent subagent review |
| Git integration | Not included | Pre-task stash/branch + step commits + PR |
| Cross-session memory | Via Hermes memory | Structured JSON: conventions, pitfalls, task history |

---

## Architecture

```
vibe "<intent>" -p <path>
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  vibe_loop.py  (7-phase agent loop)                 │
│                                                     │
│  Phase 0 ── git-integration    (stash + branch)    │
│  Phase 1 ── repo-explorer      (symbol map + cache)│
│  Phase 2 ── Planning           (intent → subtasks) │
│  Phase 3 ── atomic-modify      (cross-file edits)  │
│  Phase 4 ── lsp-integration    (semantic verify)   │
│  Phase 5 ── error-recovery     (bounded retry ×3)  │
│  Phase 6 ── git-integration    (structured commit) │
│  Phase 7 ── project-memory     (save task history) │
└─────────────────────────────────────────────────────┘
```

---

## Skills

| Skill | Purpose |
|-------|---------|
| `SKILL.md` | Main vibe-coding skill — orchestrates the 7-phase loop |
| `skills/lsp-integration.skill.md` | Type-aware diagnostics via pyright / tsc / gopls / rust-analyzer |
| `skills/atomic-modify.skill.md` | Import graph + blast radius + atomic cross-file edits |
| `skills/error-recovery.skill.md` | 10-type error classifier + strategy-matched fix agent |
| `skills/repo-explorer.skill.md` | Auto project root detection + symbol map + caching |
| `skills/git-integration.skill.md` | Pre-task checkpoint, step commits, rollback, PR creation |
| `skills/project-memory.skill.md` | Cross-session conventions, pitfalls, task history |

---

## Install

**Requires [Hermes Agent](https://hermes-agent.nousresearch.com/docs/getting-started/installation) first.**

```bash
git clone https://github.com/itproco0701/hermes-vibe-coding
cd hermes-vibe-coding
bash install.sh
```

Optional but recommended tools (installed automatically if missing):

```bash
# Python semantic analysis
pip install pyright

# TypeScript dependency graph
npm install -g madge

# Fast file search
brew install ripgrep   # macOS
apt install ripgrep    # Ubuntu/Debian
```

---

## Usage

```bash
# Describe what you want — agent handles the rest
vibe "add retry logic to the API client" -p ~/myproject

# Show plan only, confirm before executing
vibe "refactor auth module to use dependency injection" --plan-only

# Roll back everything to pre-task state
vibe undo

# Check current branch and loop state
vibe status
```

Inside Hermes chat:

```
/vibe-coding "write tests for the payment service"
/vibe-coding "add OpenTelemetry tracing to all API endpoints"
```

---

## File structure

```
hermes-vibe-coding/
├── SKILL.md                          # Main skill (agentskills.io format)
├── README.md
├── install.sh                        # One-shot installer
├── .gitignore
├── scripts/
│   ├── vibe                          # CLI entry point
│   └── vibe_loop.py                  # 7-phase agent loop
└── skills/
    ├── lsp-integration.skill.md
    ├── atomic-modify.skill.md
    ├── error-recovery.skill.md
    ├── repo-explorer.skill.md
    ├── git-integration.skill.md
    └── project-memory.skill.md
```

---

## Supported languages

| Language | LSP | Import graph | Test runner |
|----------|-----|-------------|-------------|
| Python | pyright + mypy | AST-based | pytest |
| TypeScript / JS | tsc + eslint | madge | jest / vitest |
| Go | gopls + staticcheck | `go list` | `go test` |
| Rust | rust-analyzer | cargo | `cargo test` |

---

## How it compares to Claude Code

| Feature | Claude Code | This (v2) |
|---------|-------------|-----------|
| Repo map | Full auto | Auto (30min cache) |
| LSP diagnostics | Native | pyright / tsc / gopls / rust-analyzer |
| Cross-file atomicity | Native | AST graph + blast radius |
| Self-correction | Built-in | 10-type classifier, max 3 cycles |
| Git integration | Native | Full (stash, branch, commit, PR) |
| Cross-session memory | CLAUDE.md only | Structured JSON + Hermes memory API |

---

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- `git`
- `python3 >= 3.11`
- `ripgrep` (optional — faster repo mapping)

---

## License

MIT
