"""D08 — app.models package re-exports every concrete ORM class.

Pre-fix: ``from app.models import Resource`` raised ImportError
because only 14 of ~35 classes were re-exported. Now every model in
``app/models/*.py`` gets a re-export plus a slot in ``__all__``.

This test is a tripwire — if a future commit adds a new model file
without updating ``__init__.py``, the test fails immediately.
"""

from __future__ import annotations

import inspect
import pkgutil

import app.models
import pytest
from app.models.base import Base


def _expected_class_names() -> set[str]:
    """Walk every submodule of app.models and collect the names of
    classes that subclass Base."""
    out: set[str] = set()
    for mod_info in pkgutil.iter_modules(app.models.__path__):
        if mod_info.name == "base" or mod_info.name.startswith("_"):
            continue
        mod = __import__(f"app.models.{mod_info.name}", fromlist=["*"])
        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if obj is Base:
                continue
            if issubclass(obj, Base) and obj.__module__ == mod.__name__:
                out.add(name)
    return out


def test_every_model_class_is_reexported():
    expected = _expected_class_names()
    actual = {name for name in dir(app.models) if not name.startswith("_")}
    missing = expected - actual
    assert not missing, (
        f"app.models missing re-exports for {missing}. Add them to app/models/__init__.py."
    )


def test_all_list_matches_reexports():
    """`__all__` must include every re-exported model class."""
    expected = _expected_class_names()
    declared = set(app.models.__all__)
    missing = expected - declared
    assert not missing, f"app.models.__all__ missing {missing}"
