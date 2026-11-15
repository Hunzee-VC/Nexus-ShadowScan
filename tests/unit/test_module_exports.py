"""A ShadowScan module that declares ``__all__`` lists what other ShadowScan modules import from it.

CodeQL's unused-import and unused-global-variable queries look at one module at
a time: a name its own module never reads is reported unless ``__all__``
exports it, however many sibling modules import it. ``__all__`` is therefore
the declaration of a module's package interface, and a name imported from a
module that declares one, but missing from it, would come back as an alert.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "shadowscan"


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@cache
def _sources() -> dict[str, tuple[Path, ast.Module]]:
    return {
        _module_name(path): (path, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(PACKAGE.rglob("*.py"))
    }


def _declared_all(tree: ast.Module) -> list[str] | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "__all__" for target in node.targets
        ):
            assert isinstance(node.value, (ast.List, ast.Tuple)), "__all__ must be a literal list or tuple"
            values = [element.value for element in node.value.elts if isinstance(element, ast.Constant)]
            assert len(values) == len(node.value.elts), "__all__ must hold string literals only"
            return values
    return None


def _imported_from(importer: str, path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = importer if path.name == "__init__.py" else importer.rpartition(".")[0]
    base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def test_all_lists_every_name_other_modules_import() -> None:
    sources = _sources()
    exports = {name: _declared_all(tree) for name, (_, tree) in sources.items()}
    missing: dict[str, set[str]] = {}
    for importer, (path, tree) in sources.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _imported_from(importer, path, node)
            declared = exports.get(target)
            if declared is None or target == importer:
                continue
            for alias in node.names:
                # `from package import submodule` names a module, not an attribute.
                if alias.name not in declared and f"{target}.{alias.name}" not in sources:
                    missing.setdefault(target, set()).add(alias.name)
    assert {module: sorted(names) for module, names in missing.items()} == {}


def test_all_entries_are_unique_and_defined() -> None:
    for module, (_, tree) in _sources().items():
        declared = _declared_all(tree)
        if declared is None:
            continue
        assert len(declared) == len(set(declared)), module
        bound: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                bound.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        assert sorted(set(declared) - bound) == [], module
