"""Rules patched through the redaction namespace are restored, not deleted, on undo.

The namespace forwards the names that only its driven modules bind. pytest's
monkeypatch (9.2 and later) records an attribute's original value from the
target's own ``__dict__`` unless the target's type has a data descriptor for
the name; a forwarded name is in no ``__dict__`` of the namespace, so without
the descriptor an undo deleted the rule from its binding module instead of
restoring it, and every later sanitization pass in that process failed.
"""

from __future__ import annotations

import sys
import types

import pytest

from shadowscan.utils import redaction

FACADE = sys.modules["shadowscan.utils.redaction"]


def _forwarded_names() -> dict[str, tuple[types.ModuleType, ...]]:
    return {name: binders for name, binders in type(FACADE)._binders.items() if FACADE not in binders}


def test_every_forwarded_name_is_a_data_descriptor_of_the_namespace_type():
    forwarded = _forwarded_names()
    assert {"_SCAN_LINE_LIMIT", "_LONG_BLANK_RUN"} <= forwarded.keys()
    for name in forwarded:
        descriptor = vars(type(FACADE)).get(name)
        assert descriptor is not None, name
        assert hasattr(type(descriptor), "__set__") and hasattr(type(descriptor), "__delete__"), name
    # A name this module binds itself stays an ordinary module attribute.
    assert "sanitize_text" in vars(FACADE) and "sanitize_text" not in vars(type(FACADE))


@pytest.mark.parametrize("name", ["_SCAN_LINE_LIMIT", "_LONG_BLANK_RUN"])
def test_a_rule_patched_through_the_namespace_returns_to_every_binding_module_on_undo(name):
    binders = _forwarded_names()[name]
    original = getattr(redaction, name)
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(redaction, name, 7)
        # Patched again before the undo, as a test that tries several limits does.
        patch.setattr(redaction, name, 9)
        assert getattr(redaction, name) == 9
        assert all(vars(module)[name] == 9 for module in binders)
    finally:
        patch.undo()
    assert getattr(redaction, name) is original
    assert all(vars(module)[name] is original for module in binders)


def test_a_rule_deleted_through_the_namespace_leaves_every_binding_module_and_returns_on_undo():
    name = "_SCAN_LINE_LIMIT"
    binders = _forwarded_names()[name]
    original = getattr(redaction, name)
    patch = pytest.MonkeyPatch()
    try:
        patch.delattr(redaction, name)
        assert not hasattr(redaction, name)
        assert all(name not in vars(module) for module in binders)
        with pytest.raises(AttributeError):
            delattr(redaction, name)
    finally:
        patch.undo()
    assert getattr(redaction, name) is original
    assert all(vars(module)[name] is original for module in binders)
