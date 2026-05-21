"""
path_utils — workspace 路径解析工具

背景：上游 lsdefine/G-Agent PR #444 在 frontends/fsapp.py 引入了
`from path_utils import workspace_root_dir, workspace_config_dir, resolve_mykey_path`，
（历史包化前的路径工具模块，现位于 g_agent 包内）
本文件按 fsapp.py 实际调用契约提供最小可行实现，作为本仓库的兜底，
直到上游补齐。已记录的调用点（upstream/main:frontends/fsapp.py）：

    L14:  workspace_root = workspace_root_dir()                              # () -> Path
    L15:  config_root    = workspace_config_dir(workspace_root)              # (root) -> Path
    L16:  os.environ.setdefault("G_AGENT_WORKSPACE_ROOT", str(workspace_root))
    L17:  os.environ.setdefault("G_AGENT_USER_DATA_DIR", str(config_root))
    L274: resolve_mykey_path(os.environ.get("G_AGENT_WORKSPACE_ROOT"),
                             prefer_existing=True)                            # (root, *, prefer_existing) -> Path
"""

from __future__ import annotations

import os
from pathlib import Path

# 仓库根目录：本文件就放在仓库根，因此 parent 即为 root
_PKG_ROOT = Path(__file__).resolve().parent


def workspace_root_dir() -> Path:
    """返回工作区根目录。优先 G_AGENT_WORKSPACE_ROOT 环境变量，回退到本仓库根。"""
    env = os.environ.get("G_AGENT_WORKSPACE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return _PKG_ROOT


def workspace_config_dir(workspace_root) -> Path:
    """返回工作区配置目录。本仓库历史约定：mykey.py 等配置就在 root 同级。"""
    return Path(workspace_root)


def resolve_mykey_path(workspace_root=None, *, prefer_existing: bool = False) -> Path:
    """
    返回 mykey.py 的绝对路径。
    - workspace_root: 优先使用传入的根目录；None 时回退到 workspace_root_dir()
    - prefer_existing: 为 True 时，若候选不存在则尝试其它常见位置；都不在再回退到主候选
    """
    root = Path(workspace_root).expanduser().resolve() if workspace_root else workspace_root_dir()
    primary = root / "mykey.py"
    if prefer_existing and not primary.exists():
        for alt in (_PKG_ROOT / "mykey.py", Path.cwd() / "mykey.py"):
            if alt.exists():
                return alt.resolve()
    return primary
