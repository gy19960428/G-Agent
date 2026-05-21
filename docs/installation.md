# Installation

G-Agent is distributed as source. Clone the repo and install with `uv` (recommended) or `pip`.

## Prerequisites

- **Python 3.11 or 3.12** (do **not** use 3.14 — incompatible with several deps)
- **Git**
- **uv** (recommended) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Steps

```bash
git clone <YOUR_REPO_URL>/G-Agent.git
cd G-Agent

# Create venv and install core + UI extras
uv venv
uv pip install -e ".[ui]"

# Configure LLM credentials
cp mykey_template.py mykey.py
# Edit mykey.py: fill in at least one LLM provider key

# Launch an IM bot frontend (choose one)
g-agent fs        # Feishu / Lark
g-agent wechat    # Personal WeChat (iLink)
g-agent tg        # Telegram

# Or start the terminal chat / management hub
g-agent cli
g-agent hub
```

Run `g-agent list` to see all available commands.

## Updating

```bash
cd G-Agent
git pull
uv pip install -e ".[ui]"
```

## Uninstalling

```bash
rm -rf <path-to>/G-Agent
```

Delete the cloned directory. No global state is written outside the project tree.

## Troubleshooting

- **`g-agent: command not found`** — activate the venv first (`source .venv/bin/activate`), or use `python -m g_agent_cli ...`.
- **`pywebview` / desktop deps fail on Linux** — install GTK/WebKit system packages, or skip the `[ui]` extra and use a CLI/IM frontend.
- **Bot login problems** — ask G-Agent itself; the agent knows how to set up Feishu/Telegram/WeChat credentials interactively.
