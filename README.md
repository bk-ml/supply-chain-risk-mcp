# supply-chain-risk-mcp

An MCP server for open-source dependency risk assessment, built in two stages:

1. **[MCP Server](docs/mcp-server.md)** — a standalone MCP server exposing 5 tools + 1 resource that assess real supply-chain risk (CVEs, license conflicts, maintenance health) for any public npm/PyPI/Cargo/Maven package, using free, no-auth public data sources (OSV.dev, deps.dev, GitHub).
2. **[Multi-Agent PR Reviewer](docs/multi-agent-layer.md)** — a 3-agent system (Triage → Research → Synthesis) built on top of the MCP server via the real MCP protocol, with an 18-case eval suite, guardrails, and structured observability.

Each stage is a complete, standalone piece of work — read either doc on its own, or both for the full story of how one became the other.

## Why this exists

Dependency risk is a real, constant pain point in production engineering orgs, and almost nobody builds AI tooling around it despite that. Part 1 demonstrates real domain logic (CVE severity handling, license heuristics, maintenance scoring) wired into the MCP standard. Part 2 demonstrates agent orchestration and evaluation — the actual gap in most AI-adjacent portfolio projects, which tend to stop at "I called an LLM" without a measurement layer behind it.

## See it work in one command

```bash
git clone https://github.com/bk-ml/supply-chain-risk-mcp
cd supply-chain-risk-mcp
python3 -m venv .venv && source .venv/bin/activate

# Part 1 — MCP server, zero API keys needed
python scripts/run_option_a_demo.py

# Part 2 — multi-agent layer, needs a free Gemini API key (aistudio.google.com)
python scripts/run_option_b_demo.py
```

See [`docs/mcp-server.md`](docs/mcp-server.md) and [`docs/multi-agent-layer.md`](docs/multi-agent-layer.md) for full setup instructions, tool/architecture details, and everything else.

## Tagged milestones

- [`v1-mcp-server`](../../releases/tag/v1-mcp-server) — Part 1 complete, standalone, before any multi-agent work began. `git checkout v1-mcp-server` to see it in complete isolation.
- [`v2-multi-agent-system`](../../releases/tag/v2-multi-agent-system) — the full project complete: MCP server + multi-agent PR reviewer, merged, with the 18-case eval suite passing. `git checkout v2-multi-agent-system` for the final combined state.

## Repo layout

```
supply-chain-risk-mcp/
├── server.py                    # Part 1: MCP server
├── demo.py                      # Part 1: zero-config CLI demo
├── clients/, logic/              # Part 1: domain logic
├── agents/, orchestration/       # Part 2: multi-agent system
├── evals/                        # Part 2: eval suite + results
├── scripts/                      # One-command demos for both parts
├── tests/                        # unit/ + integration/
├── docs/
│   ├── mcp-server.md             # Part 1 — full docs
│   ├── multi-agent-layer.md      # Part 2 — full docs
│   └── screenshots/
├── SCORING.md                    # Part 1's risk-scoring methodology
└── README.md                     # This file
```