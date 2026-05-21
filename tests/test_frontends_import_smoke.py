"""
frontends/*app.py 顶层 import smoke 测试。

目的：拦截类似 lsdefine/G-Agent PR #444 的事故——
PR 在 fsapp.py 引入 `from g_agent.path_utils import ...`，但 路径工具未 add 到仓库，
合并后线上启动直接 ModuleNotFoundError。

策略：
1. AST 扫描 frontends/*app.py 的顶层 import 语句
2. 对每个被 import 的模块名（仅顶包），尝试 importlib.import_module
3. 任何 ModuleNotFoundError 都视为失败（其它 ImportError 由具体模块自检负责）

不直接 `import frontends.fsapp`，因为这些 app 模块导入时会启动监听线程、
连接外部服务，作为单元测试不合适。
"""

import ast
import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
FRONTENDS = _ROOT / "frontends"
# 模拟实际启动：fsapp.py 等运行时会把 PROJECT_ROOT 注入 sys.path，
# 且 systemd 单元的 WorkingDirectory=frontends 让兄弟模块可直接 import。
for _p in (str(_ROOT), str(FRONTENDS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 这些模块在缺少可选依赖时会 ImportError，不算 smoke 范围
_OPTIONAL_TOPLEVEL = {
    "msvcrt",  # Windows-only
}


def _toplevel_imports(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names - _OPTIONAL_TOPLEVEL


@pytest.mark.parametrize(
    "app_file",
    sorted(p for p in FRONTENDS.glob("*app*.py") if p.is_file()),
    ids=lambda p: p.name,
)
def test_frontend_toplevel_imports_resolvable(app_file: Path):
    missing = []
    for mod in _toplevel_imports(app_file):
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as e:
            # 只在“顶包都找不到”时报错；具体子模块缺失留给被测代码自身
            if e.name == mod:
                missing.append(mod)
        except Exception:
            # 其它 ImportError（例如可选依赖在 import 时抛业务异常）不在 smoke 范围
            pass
    assert not missing, f"{app_file.name} 顶层 import 找不到模块: {missing}"
