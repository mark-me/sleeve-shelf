"""The layers of the code, as CLAUDE.md describes them: each may only import those below it."""

import ast
from pathlib import Path

import sleeve_shelf

ROOT = Path(sleeve_shelf.__file__).parent
# What each package may use, besides itself. `web` and the command line tie everything together.
ALLOWED = {
    "domain": set(),
    "sorting": {"domain"},
    "ingestion": {"domain"},
    "persistence": {"domain"},
    "config": {"domain"},
    "access": {"config"},
    "library": {"domain", "persistence", "sorting", "ingestion", "config"},
    "shelving": {"domain", "persistence", "sorting", "config", "library"},
    "fetching": {"domain", "persistence", "ingestion", "sorting", "config", "library"},
    "insights": {"domain", "persistence", "sorting", "config", "library"},
}


def _imports(path: Path) -> set[str]:
    """The packages of the app this file imports."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sleeve_shelf."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.ImportFrom) and node.module == "sleeve_shelf":
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[1] for a in node.names if a.name.startswith("sleeve_shelf."))
    return found


def test_each_layer_imports_only_what_is_below_it():
    wrong = []
    for package, allowed in ALLOWED.items():
        folder = ROOT / package
        for path in folder.rglob("*.py") if folder.is_dir() else [ROOT / f"{package}.py"]:
            wrong.extend(f"{path.relative_to(ROOT)} imports {other}" for other in _imports(path) - allowed - {package})
    assert not wrong, wrong


def test_every_part_of_the_app_has_a_place_in_the_layers():
    parts = {p.stem for p in ROOT.glob("*.py")} | {p.name for p in ROOT.iterdir() if (p / "__init__.py").exists()}
    assert parts - set(ALLOWED) == {"__init__", "__main__", "cli", "web"}


def test_the_services_do_not_need_the_web_layer():
    """Importing the package itself loads no blueprint, and with it no Flask."""
    assert (ROOT / "__init__.py").read_text(encoding="utf-8").count("import ") == 0
