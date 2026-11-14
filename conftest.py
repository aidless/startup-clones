"""根级测试配置：让 `python3 -m pytest`（在仓库根目录）一次跑完七个项目的全部测试。

两个必须在这里解决的问题：

1. `python3 -m pytest` 会把仓库根放进 sys.path，而 `cruxline/`（目录）与
   `cruxline/cruxline/`（真正的包）同名 —— 于是 `import cruxline` 先命中那个
   没有 __init__.py 的目录，变成一个"命名空间包"，子项目测试全部 ImportError。
   这里用 importlib 按文件路径显式装载真实包并写进 sys.modules，绕开这个歧义。
2. 七个项目各有自己的 pyproject（`pythonpath=["."]`），根目录跑时不会生效，
   所以把每个项目目录也插进 sys.path。
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
PROJECTS = ("geo-radar", "filing-lens", "audit-loop", "cruxline",
            "agent-inbox", "agent-store", "console")

for name in PROJECTS:
    path = str(ROOT / name)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)


def _load_explicit(pkg_name: str, pkg_dir: pathlib.Path) -> None:
    """按文件路径装载包，避免同名目录把它遮住。"""
    if pkg_name in sys.modules and getattr(sys.modules[pkg_name], "__file__", None):
        return
    init = pkg_dir / "__init__.py"
    if not init.exists():
        return
    spec = importlib.util.spec_from_file_location(
        pkg_name, init, submodule_search_locations=[str(pkg_dir)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = module
    spec.loader.exec_module(module)


_load_explicit("cruxline", ROOT / "cruxline" / "cruxline")
