"""
path_utils 单元测试：覆盖 fsapp.py 的全部调用契约。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import g_agent.path_utils as path_utils  # noqa: E402


def test_workspace_root_dir_returns_path():
    p = path_utils.workspace_root_dir()
    assert isinstance(p, Path)
    assert p.is_dir()


def test_workspace_root_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("G_AGENT_WORKSPACE_ROOT", str(tmp_path))
    assert path_utils.workspace_root_dir() == tmp_path.resolve()


def test_workspace_config_dir_returns_path():
    root = path_utils.workspace_root_dir()
    cfg = path_utils.workspace_config_dir(root)
    assert isinstance(cfg, Path)


def test_resolve_mykey_path_default():
    p = path_utils.resolve_mykey_path()
    assert isinstance(p, Path)
    assert p.name == "mykey.py"


def test_resolve_mykey_path_with_root(tmp_path):
    p = path_utils.resolve_mykey_path(tmp_path)
    assert p == (tmp_path.resolve() / "mykey.py")


def test_resolve_mykey_path_prefer_existing_fallback(tmp_path):
    # 传入空目录 + prefer_existing=True，应回退到仓库根的真实 mykey.py（若存在）
    p = path_utils.resolve_mykey_path(tmp_path, prefer_existing=True)
    assert isinstance(p, Path)
    assert p.name == "mykey.py"
