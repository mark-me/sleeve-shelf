"""The layers of the code, as CLAUDE.md describes them: each may only import those below it."""

import ast
from collections.abc import Iterator
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


MOST_LOADS_IN_A_VIEW = 4


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


def test_nothing_outside_the_web_layer_knows_flask():
    wrong = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] != "web":
            imported = {
                name.split(".")[0]
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for name in ([node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names])
            }
            if imported & {"flask", "flask_babel"}:
                wrong.append(str(relative))
    assert not wrong, wrong


def test_a_view_leaves_gathering_data_to_the_services():
    """A view reads the form and shows a page: a few lookups at most, not a whole screen's data."""
    wrong = []
    for path in (ROOT / "web").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and ast.unparse(node).count("store.load(") > MOST_LOADS_IN_A_VIEW:
                wrong.append(f"{path.name}: {node.name}")
    assert not wrong, wrong


def test_every_part_of_the_app_has_a_place_in_the_layers():
    parts = {p.stem for p in ROOT.glob("*.py")} | {p.name for p in ROOT.iterdir() if (p / "__init__.py").exists()}
    assert parts - set(ALLOWED) == {"__init__", "__main__", "cli", "web"}


def test_the_services_do_not_need_the_web_layer():
    """Importing the package itself loads no blueprint, and with it no Flask."""
    assert (ROOT / "__init__.py").read_text(encoding="utf-8").count("import ") == 0


def _is_view(node: ast.FunctionDef) -> bool:
    return any("blueprint" in ast.unparse(decorator) for decorator in node.decorator_list)


def _documented_functions(body: list) -> Iterator[ast.FunctionDef]:
    """The public functions and the methods of public classes; views say only what they show."""
    for node in body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and not _is_view(node):
            yield node
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            yield from _documented_functions(node.body)


def test_public_functions_document_their_arguments_results_and_errors():
    """The Google style, which ruff checks only once a section is there."""
    missing = []
    for path in ROOT.rglob("*.py"):
        for node in _documented_functions(ast.parse(path.read_text(encoding="utf-8")).body):
            doc = ast.get_docstring(node) or ""
            where = f"{path.relative_to(ROOT)}: {node.name}"
            if any("property" in ast.unparse(decorator) for decorator in node.decorator_list):
                continue
            if [a for a in node.args.args + node.args.kwonlyargs if a.arg not in ("self", "cls")] and "Args:" not in doc:
                missing.append(f"{where} has no Args")
            if node.returns is not None and ast.unparse(node.returns) != "None" and "Returns:" not in doc:
                missing.append(f"{where} has no Returns")
            if any(isinstance(inner, ast.Raise) for inner in ast.walk(node)) and "Raises:" not in doc:
                missing.append(f"{where} has no Raises")
    assert not missing, missing


def test_public_classes_document_their_fields():
    missing = []
    for path in ROOT.rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                has_fields = any(isinstance(member, ast.AnnAssign) for member in node.body)
                if has_fields and "Attributes:" not in (ast.get_docstring(node) or ""):
                    missing.append(f"{path.relative_to(ROOT)}: {node.name}")
    assert not missing, missing
