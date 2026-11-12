"""Comments and docstrings name hosts, variables and models without using them; code is never prose."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from shadowscan.connectors.code.source_ranges import noncode_ranges
from shadowscan.connectors.code.source_text import _Prose, _prose_spans, _python_prose_spans, _without_spans

OPENAI = "https://api.openai.com/v1/models"
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
# Characters wider than one UTF-8 byte before the prose, and CRLF line breaks.
PY_WIDE_CRLF = (
    "# Déjà vu: api.openai.com is blocked.\r\n"
    "import requests\r\n"
    "\r\n"
    "def handler(event):\r\n"
    '    """Café – OPENAI_API_KEY is never read; api.anthropic.com neither."""\r\n'
    '    return requests.get("https://internal.example/health").status_code  # not api.openai.com\r\n'
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
R_NOTEBOOK = json.dumps(
    {
        "metadata": {"kernelspec": {"name": "ir", "language": "R", "display_name": "R"}},
        "nbformat": 4,
        "nbformat_minor": 5,
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "a1",
                "metadata": {},
                "outputs": [],
                "source": ["library(httr)\n", "endpoint <-\n", f'  "{OPENAI}"\n', "GET(endpoint)\n"],
            }
        ],
    }
)
# Code that calls the provider. Recognising prose by what a lexer span starts with, or Python
# docstrings by counting brackets, read each of these as prose and reported nothing.
USAGE = {
    "py-fstring-after-interpolation": (
        "app.py",
        'import requests\nSCHEME = "https:"\nrequests.get(f"{SCHEME}//api.openai.com/v1/models")\n',
    ),
    "py-fstring-shell-script": (
        "deploy.py",
        'import subprocess\nscript = f"""#!/bin/sh\ncurl https://api.openai.com/v1/models'
        ' -H "Authorization: Bearer $OPENAI_API_KEY"\n"""\nsubprocess.run(["sh", "-c", script], check=True)\n',
    ),
    "py-escaped-braces-then-bracketed-string": (
        "client.py",
        f'import requests\nTEMPLATE = f"}}}}"\nrequests.post(\n    "{OPENAI}"\n)\n',
    ),
    "py-replacement-field-then-bracketed-string": (
        "client.py",
        'import requests\nUSER_AGENT = f"demo/{requests.__version__}"\n'
        f'ENDPOINT = (\n    "{OPENAI}"\n)\nrequests.get(ENDPOINT, headers={{"User-Agent": USER_AGENT}})\n',
    ),
    "py-docopt-default": (
        "cli.py",
        '"""Usage: cli [--base-url=<url>]\n\nOptions:\n'
        '  --base-url=<url>  API base [default: https://api.openai.com/v1]\n"""\n'
        'from docopt import docopt\nimport requests\n\nargs = docopt(__doc__)\nrequests.get(args["--base-url"] + "/models")\n',
    ),
    "ts-template-after-interpolation": (
        "models.ts",
        "export async function models(): Promise<Response> {\n"
        "  return fetch(`${window.location.protocol}//api.openai.com/v1/models`);\n}\n",
    ),
    "js-template-shell-script": (
        "deploy.js",
        'const { execSync } = require("child_process");\nexecSync(`#!/bin/sh\n'
        'curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"\n`);\n',
    ),
    "kotlin-interpolation": (
        "Client.kt",
        'val scheme = "https:"\nval url = "${scheme}//api.openai.com/v1/models"\n',
    ),
    "csharp-interpolation": (
        "Client.cs",
        'class Client {\n  const string Scheme = "https:";\n  string Url => $"{Scheme}//api.openai.com/v1/models";\n}\n',
    ),
    "dart-interpolation": (
        "client.dart",
        "const scheme = 'https:';\nfinal url = '${scheme}//api.openai.com/v1/models';\n",
    ),
    "ruby-interpolation": ("client.rb", 'SCHEME = "https:"\nURL = "#{SCHEME}//api.openai.com/v1/models"\n'),
    "swift-raw-string": ("Client.swift", f'import Foundation\nlet url = URL(string: #"{OPENAI}"#)!\n'),
    "php-template-before-script": (
        "page.php",
        f'<!-- template -->\n<script>\nfetch("{OPENAI}");\n</script>\n',
    ),
    "r-notebook": ("analysis.ipynb", R_NOTEBOOK),
}


def _scan(tmp_path: Path, run_connector, files: dict[str, str]):
    for name, content in files.items():
        (tmp_path / name).write_bytes(content.encode("utf-8"))
    findings, ctx = run_connector("code.filesystem", path=str(tmp_path), use_git=False)
    assert not ctx.stats.errors
    return findings


def _unchecked() -> None:
    return None


def _prose(source: str) -> list[str] | None:
    spans = _python_prose_spans(source, _unchecked)
    return None if spans is None else [source[start:end] for start, end in spans]


@pytest.mark.parametrize(
    "source",
    [PY_COMMENTS, PY_DOCSTRINGS, PY_WIDE_CRLF],
    ids=["comments", "docstrings", "wide-characters-and-crlf"],
)
def test_python_prose_that_names_a_provider_is_not_llm_usage(tmp_path: Path, run_connector, source):
    # Two comment lines scored a 0.99-confidence "LLM usage: OpenAI, Anthropic" finding.
    assert _scan(tmp_path, run_connector, {"proxy.py": source}) == []


@pytest.mark.parametrize("case", sorted(USAGE))
def test_code_that_calls_the_provider_is_still_usage(tmp_path: Path, run_connector, case):
    name, source = USAGE[case]
    findings = _scan(tmp_path, run_connector, {name: source})
    assert any("provider.openai" in finding.model_providers for finding in findings)


def test_other_languages_keep_reading_their_comments(tmp_path: Path, run_connector):
    # Only Python prose is known by token kind. Elsewhere a lexer span that starts with "//" can be a
    # template or interpolated piece, so comments stay evidence, as before.
    [finding] = _scan(tmp_path, run_connector, {"main.go": GO_COMMENTS})
    assert "provider.openai" in finding.model_providers


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


def test_string_statements_are_docstrings():
    source = (
        '"""Module."""\n'
        "LIMIT = 3\n"
        '"""Attribute note."""\n'
        "class Proxy:\n"
        "    b'Bytes.'\n"
        "    def run(self):\n"
        "        r'''Function.'''  # trailing comment\n"
        "        try:\n"
        "            'In a try block.'\n"
        "        except OSError:\n"
        "            'In a handler.'\n"
        "        match LIMIT:\n"
        "            case 3:\n"
        "                'In a case.'\n"
        "        return LIMIT\n"
    )
    assert _prose(source) == [
        '"""Module."""',
        '"""Attribute note."""',
        "b'Bytes.'",
        "r'''Function.'''",
        "# trailing comment",
        "'In a try block.'",
        "'In a handler.'",
        "'In a case.'",
    ]


@pytest.mark.parametrize(
    "source",
    [
        'HOST = "api.openai.com"\n',
        'client = connect(\n    "api.openai.com"\n)\n',
        'HOSTS = [\n    "api.openai.com",\n    "api.anthropic.com"\n]\n',
        'ROUTES = {"chat":\n    "api.openai.com"\n}\n',
        '"api.openai.com".lower()\n',
        'HOST = \\\n    "api.openai.com"\n',
        'URL = f"{SCHEME}//api.openai.com"\n',
        'SCRIPT = f"""#!/bin/sh\ncurl https://api.openai.com"""\n',
        'TEMPLATE = f"}}"\nrequests.post(\n    "https://api.openai.com"\n)\n',
        'AGENT = f"demo/{version}"\nENDPOINT = (\n    "https://api.openai.com"\n)\n',
        # An f-string statement runs the code in its replacement fields.
        'f"{register()} api.openai.com"\n',
    ],
)
def test_strings_the_code_reads_are_not_prose(source):
    assert _prose(source) == []


def test_a_comment_between_the_parts_of_a_docstring_is_one_span():
    source = "(\n    'Part one, '  # api.openai.com\n    'part two.'\n)\n"
    assert _prose(source) == ["'Part one, '  # api.openai.com\n    'part two.'"]


def test_offsets_count_characters_not_bytes():
    assert _prose(PY_WIDE_CRLF) == [
        "# Déjà vu: api.openai.com is blocked.",
        '"""Café – OPENAI_API_KEY is never read; api.anthropic.com neither."""',
        "# not api.openai.com",
    ]


def test_a_file_that_reads_its_docstring_keeps_it():
    source = (
        '"""Usage: cli [--url=<u>] [default: https://api.openai.com]"""\n'
        "import docopt\n"
        "ARGS = docopt.docopt(__doc__)  # parse\n"
    )
    assert _prose(source) == ["# parse"]


@pytest.mark.parametrize(
    "source",
    [
        "def broken(:\n    # api.openai.com\n",
        "x = 1\r# a bare carriage return is a line break to Python\n",
        "x = '\x00'  # api.openai.com\n",
        "print 'python 2'  # api.openai.com\n",
    ],
    ids=["syntax-error", "bare-carriage-return", "nul", "python-2"],
)
def test_prose_that_cannot_be_known_exactly_is_unknown(source):
    assert _python_prose_spans(source, _unchecked) is None


def test_only_python_files_have_exact_prose():
    js = '"use strict";\n// api.openai.com\nconst host = "api.openai.com";\n'
    ignored, _ = noncode_ranges(js, "javascript", ".js")
    assert _prose_spans(js, ignored, ".js", False, _unchecked) == ([(14, 31)], False)
    py = "HOST = 'api.openai.com'  # api.anthropic.com\n"
    ignored, _ = noncode_ranges(py, "python", ".py")
    assert _prose_spans(py, ignored, ".py", False, _unchecked) == ([(25, 44)], True)
    assert _prose_spans(py, ignored, ".py", True, _unchecked) == ([(25, 44)], False)
    # A span the lexer merged from a comment and a string is never exact, so it hides nothing.
    merged = 'const ENDPOINT = /* prod */"https://api.openai.com";\n'
    assert _prose_spans(merged, [(17, 51)], ".js", False, _unchecked) == ([(17, 51)], False)


def test_blanking_keeps_offsets_and_lines():
    source = 'a = 1  # one\r\n"""two\r\nlines"""\r\nb = "three"\r\n'
    ignored, _ = noncode_ranges(source, "python", ".py")
    spans, exact = _prose_spans(source, ignored, ".py", False, _unchecked)
    assert exact
    blanked = _without_spans(source, spans)
    assert len(blanked) == len(source)
    assert blanked == 'a = 1       \r\n      \r\n        \r\nb = "three"\r\n'
    assert _without_spans(source, []) is source


def test_classifying_charges_the_input_budget():
    calls: list[None] = []
    _python_prose_spans("x = 1  # c\n" * 10_000, lambda: calls.append(None))
    # Five tokens a line: the budget is checked before parsing and every 4,096 tokens after.
    assert len(calls) >= 50_000 // 4096


def test_a_spent_budget_stops_classifying():
    class Spent(Exception):
        pass

    def spent() -> None:
        raise Spent

    with pytest.raises(Spent):
        _python_prose_spans("x = 1  # c\n", spent)


def test_a_large_file_is_classified_fast():
    # A text slice per candidate string made a 980 KB file run past the 8-second budget.
    unit = 'def handler_{0}(event):\n    """Handler {0}."""  # api.openai.com\n    return {0}\n\n'
    source = "".join(unit.format(index) for index in range(14_000))
    assert len(source) > 900_000
    started = time.process_time()
    spans = _python_prose_spans(source, _unchecked)
    assert time.process_time() - started < 5
    # A docstring and a comment for each handler.
    assert spans is not None and len(spans) == 28_000


class _HostIndex:
    """A stand-in signature index: every line that names api.openai.com is one host match."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def match_envs_in_text(self, text: str) -> list[SimpleNamespace]:
        return []

    def match_domains_in_text(self, text: str, *, skip_line=None, source=False) -> list[SimpleNamespace]:
        self.texts.append(text)
        return [
            SimpleNamespace(line=n) for n, line in enumerate(text.split("\n"), 1) if "api.openai.com" in line
        ]


def _evidence(source: str) -> tuple[list[int], int, int]:
    """The host lines found in ``source``, how often it was matched and how often classification checked."""
    checks: list[None] = []
    ignored, _ = noncode_ranges(source, "python", ".py")
    prose = _Prose(source, ignored, ".py", False, lambda: checks.append(None))
    index = _HostIndex()
    _, hosts, _ = prose.evidence(source, index, None, source=True)  # type: ignore[arg-type]
    return [host.line for host in hosts], len(index.texts), len(checks)


def test_a_file_whose_matches_avoid_its_prose_is_neither_classified_nor_matched_twice():
    # A large module pays for parsing only when a host or variable name sits on a masked line.
    assert _evidence("import os\nx = 1  # local only\n") == ([], 1, 0)
    assert _evidence("api.openai.com.ping()\n# a comment elsewhere\n") == ([1], 1, 0)


def test_a_match_on_a_masked_line_is_matched_again_without_the_prose():
    lines, matched, checks = _evidence("# api.openai.com is blocked\nx = 1\n")
    assert (lines, matched) == ([], 2) and checks
    lines, matched, checks = _evidence('URL = "https://api.openai.com"  # api.openai.com\n')
    assert (lines, matched) == ([1], 2) and checks


def test_other_files_are_never_classified():
    checks: list[None] = []
    prose = _Prose("# api.openai.com\n", [(0, 16)], ".go", False, lambda: checks.append(None))
    _, hosts, _ = prose.evidence("# api.openai.com\n", _HostIndex(), None, source=True)  # type: ignore[arg-type]
    assert [host.line for host in hosts] == [1]
    assert not checks
    assert [
        host.line for host in _Prose().evidence("api.openai.com\n", _HostIndex(), None, source=False)[1]
    ] == [1]  # type: ignore[arg-type]


def test_the_model_pass_classifies_on_first_read_and_only_once():
    checks: list[None] = []
    source = "x = 1  # gpt-4o\n"
    ignored, _ = noncode_ranges(source, "python", ".py")
    prose = _Prose(source, ignored, ".py", False, lambda: checks.append(None))
    assert not checks
    assert list(prose) == [(7, 15)] and len(prose) == 1 and prose[0] == (7, 15)
    classified = len(checks)
    assert classified
    assert list(prose) == [(7, 15)]
    assert len(checks) == classified


def test_text_without_comments_or_quotes_is_not_parsed():
    def spent() -> None:
        raise AssertionError("parsed")

    assert (
        _python_prose_spans("def handler(request):\n    return client.chat(model=request.m)\n", spent) == []
    )
