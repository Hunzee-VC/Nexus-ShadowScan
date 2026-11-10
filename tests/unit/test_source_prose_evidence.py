"""Comments and docstrings name hosts, variables and models without using them."""

from __future__ import annotations

from pathlib import Path

import pytest

from shadowscan.connectors.code.source_ranges import noncode_ranges
from shadowscan.connectors.code.source_text import _prose_spans, _python_docstring_spans, _without_spans

PY_COMMENTS = (
    "import requests\n"
    "\n"
    "# This service must never call api.openai.com or api.anthropic.com.\n"
    "# OPENAI_API_KEY and ANTHROPIC_API_KEY are blocked at the proxy.\n"
    "\n"
    "def handler(event):\n"
    '    return requests.get("https://internal.example/health").status_code\n'
)
PY_DOCSTRINGS = (
    '"""Deny list notes: api.openai.com and api.anthropic.com are blocked."""\n'
    "import requests\n"
    "\n"
    "class Proxy:\n"
    '    r"""Rejects requests that carry OPENAI_API_KEY or name "gpt-4o"."""\n'
    "\n"
    "    def handler(self, event):\n"
    "        '''Calls nothing at api.anthropic.com.'''\n"
    '        return requests.get("https://internal.example/health").status_code\n'
)
GO_COMMENTS = (
    "package main\n"
    "\n"
    "// This service must never call api.openai.com or api.anthropic.com.\n"
    "/* OPENAI_API_KEY is blocked at the proxy. */\n"
    "func main() {\n"
    '\tprintln("ok")\n'
    "}\n"
)
TS_COMMENTS = (
    "// Requests to api.openai.com are rejected upstream.\n"
    "/**\n"
    " * ANTHROPIC_API_KEY is never read here; api.anthropic.com is unreachable.\n"
    " */\n"
    "export const health = (): string => 'ok';\n"
)
PY_USAGE_AFTER_NOTE = (
    "import os\n"
    "import requests\n"
    "\n"
    "# api.openai.com is the only provider this job may reach.\n"
    "def ask(question):\n"
    '    """Send one question to api.openai.com."""\n'
    "    return requests.post(\n"
    '        "https://api.openai.com/v1/chat/completions",  # see the note above\n'
    '        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},\n'
    '        json={"model": "gpt-4o", "messages": [{"role": "user", "content": question}]},\n'
    "    ).json()\n"
)


def _scan(tmp_path: Path, run_connector, files: dict[str, str]):
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    findings, ctx = run_connector("code.filesystem", path=str(tmp_path), use_git=False)
    assert not ctx.stats.errors
    return findings


def _docstrings(source: str) -> list[str]:
    ignored, incomplete = noncode_ranges(source, "python", ".py")
    assert not incomplete
    return [source[start:end] for start, end in _python_docstring_spans(source, ignored)]


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("notes.py", PY_COMMENTS),
        ("proxy.py", PY_DOCSTRINGS),
        ("main.go", GO_COMMENTS),
        ("health.ts", TS_COMMENTS),
    ],
)
def test_prose_that_names_a_provider_is_not_llm_usage(tmp_path: Path, run_connector, name, source):
    # Two comment lines scored a 0.99-confidence "LLM usage: OpenAI, Anthropic" finding.
    assert _scan(tmp_path, run_connector, {name: source}) == []


def test_usage_beside_prose_is_still_found_at_the_code_line(tmp_path: Path, run_connector):
    [finding] = _scan(tmp_path, run_connector, {"ask.py": PY_USAGE_AFTER_NOTE})
    assert "provider.openai" in finding.model_providers
    locations = {evidence.location for evidence in finding.evidence}
    assert {"ask.py:8", "ask.py:9", "ask.py:10"} <= locations
    assert not locations & {"ask.py:4", "ask.py:6"}


def test_a_link_in_a_comment_is_not_a_potential_provider(tmp_path: Path, run_connector):
    source = "from openai import OpenAI\n\n# weights: https://huggingface.co/meta-llama/Llama-3-8b\nclient = OpenAI()\n"
    [finding] = _scan(tmp_path, run_connector, {"app.py": source})
    assert finding.model_providers == ["provider.openai"]
    assert "potential_providers" not in finding.metadata


def test_a_string_statement_is_a_docstring():
    source = (
        '"""Module."""\n'
        "import os\n"
        "LIMIT = 3\n"
        '"""Attribute note."""\n'
        "def run():\n"
        "    r'''Function.'''  # trailing comment\n"
        "    return LIMIT\n"
    )
    assert _docstrings(source) == ['"""Module."""', '"""Attribute note."""', "r'''Function.'''"]


@pytest.mark.parametrize(
    "source",
    [
        'HOST = "api.openai.com"\n',
        'client = connect(\n    "api.openai.com"\n)\n',
        'HOSTS = [\n    "api.openai.com",\n    "api.anthropic.com"\n]\n',
        'ROUTES = {"chat":\n    "api.openai.com"\n}\n',
        '"api.openai.com".lower()\n',
        'HOST = \\\n    "api.openai.com"\n',
        'print("a"); "api.openai.com"\n',
        'broken = (\n"api.openai.com"\n',
    ],
)
def test_a_string_the_code_reads_is_not_a_docstring(source):
    assert _docstrings(source) == []


def test_only_python_strings_are_docstrings():
    source = '"use strict";\n// api.openai.com\nconst host = "api.openai.com";\n'
    ignored, _ = noncode_ranges(source, "javascript", ".js")
    assert [source[start:end] for start, end in _prose_spans(source, ignored, "javascript")] == [
        "// api.openai.com"
    ]


def test_blanking_keeps_offsets_and_lines():
    source = 'a = 1  # one\n"""two\nlines"""\nb = "three"\n'
    ignored, _ = noncode_ranges(source, "python", ".py")
    blanked = _without_spans(source, _prose_spans(source, ignored, "python"))
    assert len(blanked) == len(source)
    assert blanked.count("\n") == source.count("\n")
    assert blanked == 'a = 1       \n      \n        \nb = "three"\n'
    assert _without_spans(source, []) is source
