"""D13 — workflow YAML parser refuses alias bombs.

`yaml.safe_load` is safe against arbitrary code exec but not against
the billion-laughs alias expansion. Workflow definitions never need
anchors / aliases (steps are flat), so the parser refuses them at
load time.
"""

from __future__ import annotations

import pytest
from app.engine.parser import parse_workflow_string

pytestmark = pytest.mark.service


def test_plain_yaml_workflow_parses():
    src = """
    name: hello-world
    steps:
      - name: echo
        command: echo hello
    """
    out = parse_workflow_string(src)
    assert out["name"] == "hello-world"
    assert out["steps"][0]["name"] == "echo"


def test_yaml_alias_bomb_rejected():
    """The classic billion-laughs payload: 9 levels of alias references.

    Must raise instead of expanding to gigabytes.
    """
    payload = (
        'a: &a ["x","x","x","x","x","x","x","x","x"]\n'
        "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
        "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
        "steps: [*c]\n"
        "name: bomb\n"
    )
    with pytest.raises(Exception) as exc:
        parse_workflow_string(payload)
    # Either our custom ConstructorError or any yaml error is acceptable
    # — point is the input does NOT get fully materialised.
    assert "alias" in str(exc.value).lower() or "yaml" in type(exc.value).__name__.lower()


def test_yaml_simple_anchor_rejected():
    """A document with a top-level alias reference must be rejected."""
    payload = "name: x\ncommon: &common\n  command: echo hi\nsteps:\n  - <<: *common\n    name: s\n"
    with pytest.raises(Exception):
        parse_workflow_string(payload)
