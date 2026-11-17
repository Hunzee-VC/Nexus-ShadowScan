"""Python source ranges: unclosed literals mask only their own text, in linear time."""

from __future__ import annotations

import pytest

from shadowscan.connectors.code import source_ranges
from shadowscan.connectors.code.source_ranges import noncode_ranges


@pytest.mark.parametrize(
    "source, ambiguous",
    [
        ("x = '''never closed\nimport openai\n", False),  # EOF in a multi-line literal masks the rest
        ("import openai\nx = (1,\n", False),
    ],
)
def test_python_eof_errors_remain_unambiguous(source, ambiguous):
    spans, flagged = noncode_ranges(source, "python")
    assert flagged is ambiguous


def test_unclosed_one_line_string_masks_only_its_line():
    # Python 3.11 tokenizes past an unclosed one-line literal (ERRORTOKEN);
    # 3.12+ raises TokenError there. Both must mask that line only and keep
    # scanning the rest of the file as complete coverage.
    source = (
        'a = "never closed; StateGraph(\n'
        "import openai\n"
        "b = 'also open\n"
        "from langgraph.graph import StateGraph\n"
    )
    spans, flagged = noncode_ranges(source, "python")
    assert flagged is False

    def masked(index: int) -> bool:
        return any(start <= index < end for start, end in spans)

    assert masked(source.index("StateGraph(")) and masked(source.index("also open"))
    assert not masked(source.index("import openai")) and not masked(source.index("from langgraph"))
    assert not masked(source.index("a = ")) and not masked(source.index("b = "))


def test_many_unclosed_one_line_strings_reuse_a_single_reader(monkeypatch):
    # Recreating StringIO from every remaining suffix makes malformed source
    # quadratic within the normal one-megabyte file limit.
    source = ('value = "never closed; StateGraph(\n' * 8_000) + "import openai\n"
    original = source_ranges.io.StringIO
    allocations = []

    def tracked_reader(value):
        allocations.append(len(value))
        return original(value)

    with monkeypatch.context() as patch:
        patch.setattr(source_ranges.io, "StringIO", tracked_reader)
        spans, incomplete = noncode_ranges(source, "python")
    assert allocations == [len(source)]
    assert not incomplete and len(spans) == 8_000
    assert not any(start <= source.index("import openai") < end for start, end in spans)


def test_unclosed_python_quote_with_standalone_cr_preserves_later_code():
    # API-mode source bytes can contain CR-only line endings, even though
    # local text files normally get universal-newline conversion by open().
    source = 'x = "inert StateGraph(\rimport openai\r'
    spans, incomplete = noncode_ranges(source, "python")
    assert not incomplete
    assert any(start <= source.index("StateGraph(") < end for start, end in spans)
    assert not any(start <= source.index("import openai") < end for start, end in spans)


def test_python_comment_ends_at_a_standalone_cr():
    # CR-only source is valid Python: the comment stops at the CR and the import after it is code.
    source = "# inert note\rimport openai\rx = 1  # trailing\r"
    spans, incomplete = noncode_ranges(source, "python")
    assert not incomplete
    assert [source[start:end] for start, end in spans] == ["# inert note", "# trailing"]


def test_resumed_python_lexing_keeps_offsets_after_unicode_separators():
    source = 'x = "inert\u2028junk\u2028junk2\nimport openai; API_KEY="opaque-credential"\n'
    spans, incomplete = noncode_ranges(source, "python")
    assert not incomplete
    assert not any(start <= source.index("import openai") < end for start, end in spans)
    secret_start = source.index("opaque-credential")
    assert any(
        start <= secret_start and secret_start + len("opaque-credential") <= end for start, end in spans
    )


def test_python_tokenizer_charges_the_matching_budget_mid_line(monkeypatch):
    # The C tokenizer runs without a Python check point and is quadratic on one long
    # logical line in CPython 3.12.0 to 3.12.3. The loop must charge the per-input budget
    # between tokens, so a single-line file cannot run unbounded: patch the budget hook to
    # fire after a few blocks and confirm tokenizing one long line surfaces the timeout.
    from shadowscan.signatures.matcher import MatchTimeoutError

    calls = 0

    def fake_pattern_timeout(default: float = 0.0) -> float:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise MatchTimeoutError("budget exhausted")
        return default

    monkeypatch.setattr(source_ranges, "pattern_timeout", fake_pattern_timeout)
    # One logical line with far more than 3 * 1024 tokens and no newline to resume at.
    source = "x=[" + "0," * 20_000 + "]\n"
    with pytest.raises(MatchTimeoutError):
        noncode_ranges(source, "python")
    assert calls >= 3


def test_short_python_file_does_not_exhaust_the_budget(monkeypatch):
    # A normal file tokenizes within one budget block, so the scan stays complete.
    calls = 0

    def counting_pattern_timeout(default: float = 0.0) -> float:
        nonlocal calls
        calls += 1
        return default

    monkeypatch.setattr(source_ranges, "pattern_timeout", counting_pattern_timeout)
    _, ambiguous = noncode_ranges("import openai\nx = client()\n", "python")
    assert ambiguous is False and calls >= 1


@pytest.mark.parametrize(
    "fault",
    [
        SystemError("<built-in method __new__> returned a result with an exception set"),
        AttributeError("type object 'TokenInfo' has no attribute '_make'"),
    ],
    ids=lambda fault: type(fault).__name__,
)
def test_a_tokenizer_fault_masks_the_rest_of_the_file_and_reports_it_incomplete(monkeypatch, fault):
    # CPython 3.12's tokenizer fails for a NUL byte after an indented line with one of these, whichever
    # the process's caches make first notice (found by the fuzzing in #259). Simulated here so
    # every interpreter runs the path.
    real = source_ranges.tokenize.generate_tokens

    def faulty(readline):
        for index, token in enumerate(real(readline)):
            if index == 3:
                raise fault
            yield token

    source = "\"a\" + 'b'\nimport openai\n"
    monkeypatch.setattr(source_ranges.tokenize, "generate_tokens", faulty)
    spans, incomplete = noncode_ranges(source, "python")
    assert incomplete
    # The strings read before the fault stay masked, and so does everything after the last token read.
    assert spans == [(0, 3), (6, 9), (9, len(source))]


def test_nul_on_the_line_after_an_indented_one_is_lexed_on_every_interpreter():
    # The reproducer of the fault above: an exception on CPython 3.12, TokenError on 3.13 and fine on 3.11.
    spans, _ = noncode_ranges('\t""\n\x00', "python")
    assert (1, 3) in spans


def test_a_codec_error_from_the_tokenizer_masks_the_rest_and_reports_it_incomplete(monkeypatch):
    # shadowscan.utils.python_tokens passes the tokenizer's UnicodeError through as a documented error,
    # so the lexer answers it as it answers a fault. CPython 3.12 raises UnicodeDecodeError for valid
    # text (see the next test); simulated here so every interpreter runs the path.
    real = source_ranges.tokenize.generate_tokens

    def faulty(readline):
        for index, token in enumerate(real(readline)):
            if index == 3:
                raise UnicodeDecodeError("utf-8", b"\xef", 0, 1, "unexpected end of data")
            yield token

    source = "\"a\" + 'b'\nimport openai\n"
    monkeypatch.setattr(source_ranges.tokenize, "generate_tokens", faulty)
    spans, incomplete = noncode_ranges(source, "python")
    assert incomplete
    assert spans == [(0, 3), (6, 9), (9, len(source))]


# A multi-byte character before a backslash line break inside an f-string's replacement field. CPython
# 3.12's tokenizer raises UnicodeDecodeError on these (found by the lexing fuzz target on main,
# 2026-11-15); 3.11 and 3.13 raise TokenError.
TOKENIZER_CODEC_FAULTS = ["f'''{=f'�\\\r\n':�", "f\"{=f'\U0001f600\\\r'}﻿"]


@pytest.mark.parametrize("trigger", TOKENIZER_CODEC_FAULTS, ids=["crlf", "cr"])
def test_the_codec_fault_keeps_the_code_before_it_on_every_interpreter(trigger):
    # Before the fix, a file ending in one of these lost every finding on CPython 3.12: the error left
    # the lexer and the whole file was dropped as incomplete, its real usage included.
    code = "import openai\nclient = openai.OpenAI()\n"
    spans, _ = noncode_ranges(code + trigger, "python")
    assert all(0 <= start < end <= len(code + trigger) for start, end in spans)
    assert not any(start < len(code) for start, _ in spans)
