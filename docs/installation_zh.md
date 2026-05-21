# 安装指南

G-Agent 以源码形式分发。克隆仓库后用 `uv`（推荐）或 `pip` 安装。

## 环境要求

- **Python 3.11 或 3.12**（**不要**用 3.14，多处依赖不兼容）
- **Git**
- **uv**（推荐）：`curl -LsSf https://astral.sh/uv/install.sh | sh`

## 安装步骤

```bash
git clone <YOUR_REPO_URL>/G-Agent.git
cd G-Agent

# 创建虚拟环境并安装核心 + UI 依赖
uv venv
uv pip install -e ".[ui]"

# 配置 LLM 凭据
cp mykey_template.py mykey.py
# 编辑 mykey.py：至少填一个 LLM 提供商的 Key

# 启动一个 IM Bot 前端（任选其一）
g-agent fs        # 飞书 / Lark
g-agent wechat    # 个人微信（iLink）
g-agent tg        # Telegram

# 或者进终端对话 / 打开管理面板
g-agent cli
g-agent hub
```

执行 `g-agent list` 查看完整命令表。

## 更新

```bash
cd G-Agent
git pull
uv pip install -e ".[ui]"
```

## 卸载

```bash
rm -rf <path-to>/G-Agent
```

直接删除克隆目录即可，项目不会在项目目录之外写入任何全局状态。

## 排查

- **`g-agent: command not found`**：先激活虚拟环境（`source .venv/bin/activate`），或者改用 `python -m g_agent_cli ...`。
- **Linux 上 `pywebview` 等桌面依赖装不上**：装系统的 GTK/WebKit 包，或者干脆跳过 `[ui]` extra，只用 CLI / IM 前端。
- **Bot 登录问题**：直接问 G-Agent 自己——Agent 知道飞书 / Telegram / 微信的凭据如何交互式配置。
