import importlib
import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("PERSISTENCE_BACKEND", "inmemory")
os.environ.setdefault("VECTOR_BACKEND", "stub")

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for name in list(sys.modules):
    if name == "tools" or name.startswith("tools."):
        sys.modules.pop(name, None)
importlib.invalidate_caches()

def _bind_local_package(package_name: str) -> None:
    package_init = ROOT / package_name / "__init__.py"
    if not package_init.exists():
        return
    spec = importlib.util.spec_from_file_location(
        package_name,
        str(package_init),
        submodule_search_locations=[str(ROOT / package_name)],
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)


_bind_local_package("tools")
_bind_local_package("llm")
