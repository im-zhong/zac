# ZAC — Zhong's Agentic Coding

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) plugin for **Human-In-The-Loop iterative development** with progressive disclosure and deterministic workflow orchestration.

ZAC automates the scaffold → implement → verify cycle so you can focus on what matters — deciding *what* to build, not *how* to run the loop.

## How It Works

ZAC implements a **state machine** that chains Claude Code background sessions together via Stop hooks:

```
scaffold → autopilot → run ──┐
                              │
                     claude -p decision
                              │
                  ┌───────────┴───────────┐
                  │                       │
             more F-Ns               all done
                  │                       │
                  ▼                       ▼
             autopilot → run         summarize → done
             (next item)  (verify)
```

1. **scaffold** — Set up project context and generate the feature breakdown
2. **autopilot** — Implement the next feature point (F-N) autonomously
3. **run** — Verify: lint, type-check, test, edge cases, commit
4. **decide** — After `run`, a lightweight `claude -p` call checks if more feature points remain
5. **summarize** — All features done; generate final summary and update roadmap

Each phase runs as an isolated `claude --bg` session. When a session ends, the Stop hook reads `.zac/sessions.json`, identifies which phase just finished, and automatically launches the next one. On `StopFailure`, the same phase is retried (up to 3 times).

## Installation

### Option 1: Install from marketplace (recommended)

Add the marketplace first, then install the plugin:

```bash
# Add the marketplace
claude plugin marketplace add im-zhong/zac

# Install the plugin from marketplace
claude plugin install zac@zhongs-plugin-marketplace
```

### Option 2: Install from official marketplace

```bash
# Install from the official Claude Code marketplace
claude plugin install zac
```

### Post-install (recommended)

```bash
# Install LSP servers
npm install -g typescript-language-server typescript
npm install -g pyright
```

## Update

```bash
claude plugin marketplace update zhongs-plugin-marketplace
claude plugin uninstall zac@zhongs-plugin-marketplace
claude plugin install zac@zhongs-plugin-marketplace
```

## Usage

### Start a dev flow

```
/zac:start-dev                    # Start from scaffold
/zac:start-dev --phase autopilot  # Resume from a specific phase
/zac:start-dev --phase run --retry # Retry a failed phase
```

### Check project status

```
/zac:dev-status          # Current iteration, cycle history, document index
/zac:dev-status iter 2   # Jump to iteration 2 details
```

### Study a topic

```
/zac:study React Server Components
/zac:study "Python async/await" --mode autonomous
```

## Skills

| Skill | Description |
|-------|-------------|
| `start-dev` | Launch the automated dev-flow workflow |
| `scaffold` | Set up project context and feature breakdown |
| `dev-loop` | Autonomous develop-and-verify loop for a single item |
| `run` | Quality gate: lint, type-check, test, edge cases, commit |
| `fix` | Fix issues found during verification |
| `progressive-plan` | Progressive planning with iterative refinement |
| `pre-dev` | Pre-development setup and context gathering |
| `dev-status` | Read-only project state viewer |
| `summarize` | Generate iteration summary and update roadmap |
| `study` | Research a topic with interactive teaching and demos |
| `e2e-walkthrough` | End-to-end walkthrough of a feature |

## Architecture

```
zac/                              ← Plugin root
├── .claude-plugin/
│   └── plugin.json               ← Plugin manifest
├── scripts/
│   ├── start-dev.sh              ← Launch a dev-flow phase as bg session
│   └── stop-hook.sh              ← Handle Stop/StopFailure, drive state machine
├── skills/
│   ├── start-dev/SKILL.md
│   ├── scaffold/SKILL.md
│   ├── dev-loop/SKILL.md
│   ├── run/SKILL.md
│   ├── fix/SKILL.md
│   ├── progressive-plan/SKILL.md
│   ├── pre-dev/SKILL.md
│   ├── dev-status/SKILL.md
│   ├── summarize/SKILL.md
│   ├── study/SKILL.md
│   └── e2e-walkthrough/SKILL.md
├── agents/
│   └── study-agent.md            ← Research & teaching agent
├── hooks/
│   └── hooks.json                ← Stop/StopFailure hook config
└── docs/
    └── superpowers/              ← Design docs
```

**Runtime state** (in your project, not the plugin):

```
<your-project>/
├── .zac/
│   └── sessions.json             ← Session ID → phase mapping + retry count
└── .omc/logs/
    └── stop-hook.log             ← Hook execution log
```

## Dependencies

ZAC leverages these Claude Code plugins:

- **superpowers** — Skill orchestration and development workflows
- **frontend-design** — Production-grade UI generation
- **context7** — Up-to-date documentation lookup
- **code-review** — Automated code review
- **code-simplifier** — Code cleanup and simplification
- **playwright** — Browser automation for testing
- **feature-dev** — Guided feature development
- **ralph-loop** — Iterative refinement loop
- **typescript-lsp** / **pyright-lsp** — Language server intelligence
- **commit-commands** — Git commit and PR workflows

## Failure Handling

| Scenario | Behavior |
|----------|----------|
| Session stops normally | Advance to next phase per state machine |
| `StopFailure` fires | Retry current phase (retry_count + 1) |
| Same phase fails 3 times | Stop workflow, log error, wait for human intervention |
| Untracked session stops | Ignored — only tracked sessions drive transitions |

## License

MIT
