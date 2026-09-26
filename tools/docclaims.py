# SPDX-License-Identifier: MIT
#
# This notice is here so that a copy of this one file, which the README
# offers as a way to use it, carries its licence with it.
#
# MIT License
#
# Copyright (c) 2026 Jhane
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""docclaims - the numbers your README states, checked against where they come from.

A number written into a document is a claim that nothing re-runs. "120 tests",
"covers 30 regions", "12.5% of the variance": each was true the day it was
typed, and the test suite, the compiler and CI all stay green while it goes
quietly wrong. The usual fixes are to stop writing numbers down, or to wrap
every one in generator markup so a tool can rewrite it. This does neither. The
numbers stay plain text in the README, and a small ledger, `claims.json`, says
what each one is, how it is known, and where it comes from.

    docclaims verify .                       # every check, one repository
    docclaims verify . --scan "**/*.md"      # and find unpinned copies
    docclaims stale . --asof 2027-01-01      # claims past their re-check date
    docclaims render . --format md           # a table of every claim
    docclaims suggest README.md              # draft claims, for review

## The chain

    source --(read or recomputed)--> raw --> value --(written in)--> prose

Everything right of `raw` is text against text and imports nothing, so it runs
on a CI runner that cannot build or import the project at all.

## What `verify` checks

  schema          required fields, a status from the vocabulary, dates that
                  parse, ids that are unique, a horizon after its check date
  derived         for a claim with `derive`, the number is read out of the
                  repository's own files - a constant, a count of matches, or
                  a count of Python test methods - and must still render as
                  `value`
  rounding        `format % (raw * scale)` still renders `value`, for a number
                  some other code recomputes: a rounding change is a change to
                  a published claim, not a tolerance
  evidence        for a number that cannot be recomputed, the line in a
                  committed transcript it was read off is still there. That is
                  provenance, not verification, and the report says so
  presence        every file in `appears_in` exists and still contains `value`
  contradiction   a DIFFERENT number of the same shape sitting near the claim,
                  which is what a half-finished edit leaves behind. Needs
                  `near`; without it the report says NOT CHECKED rather than
                  passing silently
  coverage        (with --scan) a file that quotes `value` and is not listed
                  in `appears_in` - the copy nobody remembered to pin

The contradiction scan is the half that `assertIn(value, text)` cannot do.
`assertIn` asks whether the right number is present; it says nothing about a
wrong one sitting beside it, and "12.5% here, 12.4% three paragraphs down" is
exactly what editing one sentence and not the next produces.

## `derive` - counts are read, not copied

The most common stale number is a count of the project itself, and no engine
returns it, so nothing recomputes it. It is usually written in the source
already, and can be read:

    "derive": {"files": ["tests/test_*.py"], "tests": "python"}
    "derive": {"files": ["src/config.py"], "capture": "^MAX_RETRIES = (\\\\d+)"}
    "derive": {"files": ["rules/*.yaml"], "count": "^- id:"}

`capture` takes the one group of a regex that must match exactly once across
the files; twice is ambiguous and fails. `count` counts matches, line-anchored.
`tests: "python"` counts test methods on classes by parsing, not grepping,
because a test file that embeds a test file as a fixture string would count
tests that do not exist. `tests: "pytest"` counts what pytest's default
collection finds, parametrize cases included, and fails rather than guess when
a case list is not a literal.

A `capture` that is not a number is kept as text, for versions. `format` is
`%`-style, or `{}`-style when it contains a brace, which is how a thousands
separator is written: `{:,}`. A glob that matches nothing fails rather than reading
as zero. A derived claim takes `format` and no `raw`: the source is the number,
and a second copy of it in the ledger is what drifts.

`project` reads a sibling repository, found inside the root or beside it,
case-insensitively. Where it is not checked out - usually CI - the claim prints
NOT CHECKED, every run, instead of passing.

## What it does not do, on purpose

It does not discover claims. Asked which figures in a README are claims, a
tool produces a flood - years, versions, ports, HTTP statuses - and a checker
that cries wolf gets muted. Claims are declared.

It does not decide whether a claim is TRUE. `status` is the project's own
assertion about its number, and `anchor` is where a reader goes to disagree.
This checks that the assertion is stated, dated, and consistent everywhere it
appears.

Standard library only, one file, Python 3.8 or later. Copying this file into a
repository is a supported way to use it.
"""

__version__ = "0.3.3"

import argparse
import ast
import datetime
import io
import json
import pathlib
import re
import sys

#: What a project is allowed to say about how it knows a number. Deliberately
#: four, deliberately ordered weakest-last, and deliberately not extensible by
#: a caller: a vocabulary each project extends is how one repository ends up
#: saying "measured vs. estimated" in two places and "confirmed / likely" in a
#: third, meaning three different things. One vocabulary or none.
STATUSES = ("measured", "estimated", "modeled", "unconfirmed")

REQUIRED = ("id", "claim", "value", "status", "anchor", "checked_on")
OPTIONAL = ("recheck_by", "appears_in", "raw", "format", "scale", "near",
            "window", "allow", "durable", "notes", "tolerance", "evidence",
            "also_written", "derive", "todo")

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")

#: How far either side of a `near` phrase the contradiction scan looks. A
#: paragraph of HTML is frequently one very long line, so a line-scoped window
#: would miss a headline figure sitting alone in a <b> two lines above the
#: sentence that explains it.
DEFAULT_WINDOW = 300


class LedgerError(Exception):
    """The ledger file itself is unreadable or malformed."""


class Finding(object):
    """One thing `verify` has to say. Not all findings are failures."""

    def __init__(self, kind, claim_id, message, path=None, fatal=True):
        self.kind = kind
        self.claim_id = claim_id
        self.message = message
        self.path = path
        self.fatal = fatal

    def __repr__(self):
        return "<Finding %s %s%s>" % (
            self.kind, self.claim_id, "" if self.fatal else " (not fatal)")

    def as_dict(self):
        return {"kind": self.kind, "claim": self.claim_id,
                "message": self.message, "path": self.path,
                "fatal": self.fatal}

    def line(self):
        where = " [%s]" % self.path if self.path else ""
        mark = "FAIL" if self.fatal else "note"
        return "%s  %-14s %s%s: %s" % (
            mark, self.kind, self.claim_id, where, self.message)


def load(path):
    """Read a ledger file. Raises LedgerError rather than returning nothing.

    A ledger that cannot be read is not a ledger with no claims in it. An
    instrument that could not look, reporting that it found nothing, is the
    commonest way a checker lies, so a missing file never returns an empty
    list here.
    """
    path = pathlib.Path(path)
    if not path.exists():
        raise LedgerError("no ledger at %s" % path)
    try:
        with io.open(str(path), encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise LedgerError("%s is not valid JSON: %s" % (path, exc))
    if isinstance(data, dict):
        data = data.get("claims", data)
    if not isinstance(data, list):
        raise LedgerError(
            "%s must hold a list of claims, or an object with a 'claims' list"
            % path)
    return data


def load_meta(path):
    """The ledger's top-level keys other than `claims`.

    Only `exempt` today: files the coverage sweep must not report, each with a
    reason. A research log or changelog records the numbers a project got wrong
    on the way, so it is dense with superseded figures shaped exactly like the
    current claim. Scanning it produces a flood; silently not scanning it is a
    decision nobody can disagree with. So the skip is written down, with its
    reason, where somebody can.
    """
    path = pathlib.Path(path)
    if not path.exists():
        raise LedgerError("no ledger at %s" % path)
    with io.open(str(path), encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if key != "claims"}


def check_exemptions(meta, root):
    """Every exempt path exists and says why it is exempt."""
    findings = []
    exempt = meta.get("exempt")
    if exempt is None:
        return findings
    if not isinstance(exempt, dict):
        return [Finding("exempt", "-",
                        "`exempt` maps each path to WHY the sweep skips it; a "
                        "bare list is a skip nobody can disagree with")]
    root = pathlib.Path(root)
    for relative, reason in sorted(exempt.items()):
        if not str(reason).strip():
            findings.append(Finding(
                "exempt", "-", "exempts %r with no reason" % relative))
        if not (root / relative).exists():
            findings.append(Finding(
                "exempt", "-",
                "exempts a path that does not exist; a stale exemption is a "
                "hole nobody is looking through", path=relative))
    return findings


#: A number, or a dotted version read as one token rather than as a decimal
#: followed by more digits.
DOTTED = re.compile(r"\d+(?:\.\d+){2,}|\d+(?:\.\d+)?")


def shape_of(value):
    """A regex matching any number written the same way `value` is.

    "12.5%"    -> \\d+\\.\\d%       so 12.4% and 9.7% both match
    "0.4412"   -> \\d+\\.\\d{4}
    "88 rows"  -> \\d+ rows
    "v0.3.1"   -> v\\d+\\.\\d+\\.\\d+   so v0.3.0 and v1.10.2 match, v4 does not

    The decimal place count is held exactly and the integer part is not,
    because a claim changing from 12.5% to 12.54% is a formatting change the
    `rounding` check already owns, while 12.5% -> 9.7% is the drift this is
    looking for. Non-numeric text is matched literally, which is what keeps
    "88 rows" from matching every two-digit number in a file.
    """
    out = []
    last = 0
    for match in DOTTED.finditer(value):
        out.append(re.escape(value[last:match.start()]))
        whole = match.group(0)
        if whole.count(".") > 1:
            # A version, read whole. Taken as numbers, "0.3.1" is the
            # decimal 0.3 and then ".1", and the guard before the second one
            # refuses a match after a dot, so the shape could never match
            # anything, the value itself included, and a stale version beside
            # the right one was never reported. Each part may be any width;
            # how many parts there are is held.
            out.append(r"(?<![\d.])\d+(?:\.\d+){%d}(?!\.?\d)"
                       % whole.count("."))
            last = match.end()
            continue
        # Both guards are load-bearing, and the trailing one was found by
        # running this against a real repository rather than by review. A
        # four-decimal shape happily matches the leading characters of the
        # SAME claim's full-precision value sitting in a test file, so every
        # claim reported its own `raw` as a contradiction of itself.
        out.append(r"(?<![\d.])")
        if "." in whole:
            out.append(r"\d+\.\d{%d}" % len(whole.split(".", 1)[1]))
        else:
            out.append(r"\d+")
        out.append(r"(?!\d)")
        last = match.end()
    out.append(re.escape(value[last:]))
    joined = "".join(out)
    if not NUMBER.search(value):
        # A claim whose value holds no digits at all ("refuses rather than
        # guesses"). There is no shape to drift, so match only itself.
        joined = re.escape(value)
    return re.compile(joined)


WHITESPACE = re.compile(r"\s+")


def normalise(text):
    """Collapse runs of whitespace, so a claim survives a line wrap.

    Found by pointing this at a real README hard-wrapped at 79 columns: a claim
    written as several words happened to break across two lines. A literal search reported the README as not carrying a number the
    README plainly carries. Where an author chose to wrap is not a fact about
    the claim, so it must not be able to fail the check — or pass it, which is
    the worse direction: a wrap falling between two halves of a contradiction
    would hide it.
    """
    return WHITESPACE.sub(" ", text)


def excerpt(text, start, end, margin=60):
    """The matched number with enough around it to recognise the sentence."""
    left = max(0, start - margin)
    right = min(len(text), end + margin)
    return "%s%s%s" % ("..." if left else "", text[left:right],
                       "..." if right < len(text) else "")


def written_forms(claim):
    """Every rendering that counts as this claim being stated.

    One number, written two ways. Forced by a project whose README states a
    ratio in plain ASCII while its designed findings page uses a typographic
    multiplication sign. Neither is wrong and neither is a second
    claim, so the ledger holds one entry with both renderings rather than two
    entries that could drift apart — which would be this tool's own failure
    mode, one level up.

    `value` stays the canonical form: it is what `format` must produce and what
    a report prints.
    """
    forms = [claim["value"]]
    for other in claim.get("also_written") or []:
        if other not in forms:
            forms.append(other)
    return forms


def windows(text, phrases, width):
    """Character ranges around each occurrence of any phrase. Merged."""
    spans = []
    lowered = text.lower()
    for phrase in phrases:
        needle = phrase.lower()
        start = lowered.find(needle)
        while start != -1:
            spans.append((max(0, start - width),
                          min(len(text), start + len(needle) + width)))
            start = lowered.find(needle, start + 1)
    spans.sort()
    merged = []
    for span in spans:
        if merged and span[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
        else:
            merged.append(span)
    return merged


def _date(value, field, claim_id, findings):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        findings.append(Finding(
            "schema", claim_id,
            "%s is %r, which is not an ISO date (YYYY-MM-DD)"
            % (field, value)))
        return None


def check_schema(claims):
    """Everything checkable without reading a single prose file."""
    findings = []
    seen = {}
    for position, claim in enumerate(claims):
        if not isinstance(claim, dict):
            findings.append(Finding(
                "schema", "#%d" % position, "claim is not an object"))
            continue
        claim_id = claim.get("id", "#%d" % position)

        for field in REQUIRED:
            if not claim.get(field):
                findings.append(Finding(
                    "schema", claim_id, "missing required field %r" % field))

        if claim.get("todo"):
            # Written by `suggest`. A draft must fail until a person has read
            # it, or suggesting claims would be discovering them.
            findings.append(Finding(
                "schema", claim_id, "still a draft: %s" % claim["todo"]))

        unknown = set(claim) - set(REQUIRED) - set(OPTIONAL)
        for field in sorted(unknown):
            findings.append(Finding(
                "schema", claim_id,
                "unknown field %r; a typo here fails open, so it is a failure"
                % field))

        if "id" in claim:
            if not ID_PATTERN.match(str(claim["id"])):
                findings.append(Finding(
                    "schema", claim_id,
                    "id must be lowercase letters, digits and underscores"))
            if claim["id"] in seen:
                findings.append(Finding(
                    "schema", claim_id,
                    "duplicate id, also used at position %d" % seen[claim["id"]]))
            seen[claim["id"]] = position

        if claim.get("status") and claim["status"] not in STATUSES:
            findings.append(Finding(
                "schema", claim_id,
                "status %r is not one of %s"
                % (claim["status"], ", ".join(STATUSES))))

        checked = None
        if claim.get("checked_on"):
            checked = _date(claim["checked_on"], "checked_on", claim_id,
                            findings)
        if claim.get("recheck_by"):
            horizon = _date(claim["recheck_by"], "recheck_by", claim_id,
                            findings)
            if horizon and checked and horizon <= checked:
                findings.append(Finding(
                    "schema", claim_id,
                    "recheck_by %s is not after checked_on %s"
                    % (claim["recheck_by"], claim["checked_on"])))
        elif not claim.get("durable"):
            findings.append(Finding(
                "schema", claim_id,
                "no recheck_by and no `durable` reason; a claim with neither "
                "is a claim nobody has decided how long to trust"))

        derive = claim.get("derive")
        if derive is not None:
            findings.extend(_check_derive_spec(claim_id, claim, derive))
        elif ("raw" in claim) != ("format" in claim):
            findings.append(Finding(
                "schema", claim_id,
                "`raw` and `format` only mean anything together; one without "
                "the other cannot check the rounding"))

        if "scale" in claim and "raw" not in claim:
            findings.append(Finding(
                "schema", claim_id,
                "`scale` converts `raw` into published units and there is no "
                "`raw` to convert"))

        evidence = claim.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, dict) or not evidence.get("file") \
                    or not evidence.get("line"):
                findings.append(Finding(
                    "schema", claim_id,
                    "`evidence` needs a `file` and the `line` in it that the "
                    "claim was read off"))
        elif "raw" not in claim and "derive" not in claim:
            # The rule this enforces: a published number must be traceable to
            # something other than the ledger. Either code can produce it
            # again (`raw`), or a committed file records the run that did
            # (`evidence`). With neither, the ledger is the number's only
            # provenance, and a ledger that is its own evidence is a
            # restatement rather than a check.
            findings.append(Finding(
                "schema", claim_id,
                "has neither `raw` (recomputable) nor `evidence` (a line in a "
                "committed file it was read off); this file would be the only "
                "record that the number was ever produced"))

        allow = claim.get("allow")
        if allow is not None:
            if not isinstance(allow, dict):
                findings.append(Finding(
                    "schema", claim_id,
                    "`allow` maps each excused number to WHY it is legitimate; "
                    "a bare list is an exemption nobody can disagree with"))
            else:
                for excused, reason in sorted(allow.items()):
                    if not str(reason).strip():
                        findings.append(Finding(
                            "schema", claim_id,
                            "`allow` entry %r has no reason" % excused))
            if not claim.get("near"):
                findings.append(Finding(
                    "schema", claim_id,
                    "`allow` excuses matches found by the `near` scan, and "
                    "there is no `near` to scan", fatal=False))

        if claim.get("window") is not None and not claim.get("near"):
            findings.append(Finding(
                "schema", claim_id,
                "`window` sets the width of the `near` scan, and there is no "
                "`near` to scan", fatal=False))
    return findings


DERIVE_MODES = ("capture", "count", "tests")


def _check_derive_spec(claim_id, claim, derive):
    """A `derive` block names its files, one way of reading them, and a format."""
    findings = []
    if not isinstance(derive, dict):
        return [Finding("schema", claim_id,
                        "`derive` is an object: files, and one of %s"
                        % ", ".join(DERIVE_MODES))]
    files = derive.get("files")
    if not isinstance(files, list) or not files \
            or not all(isinstance(f, str) and f for f in files):
        findings.append(Finding(
            "schema", claim_id, "`derive` needs `files`, a list of globs"))
    modes = [m for m in DERIVE_MODES if m in derive]
    if len(modes) != 1:
        findings.append(Finding(
            "schema", claim_id,
            "`derive` takes exactly one of %s, and has %s"
            % (", ".join(DERIVE_MODES), ", ".join(modes) or "none")))
    unknown = set(derive) - set(DERIVE_MODES) - {"files", "project"}
    for field in sorted(unknown):
        findings.append(Finding(
            "schema", claim_id, "unknown `derive` field %r" % field))
    if derive.get("tests") not in (None,) + TEST_STYLES:
        findings.append(Finding(
            "schema", claim_id,
            "`derive.tests` is one of %s, not %r"
            % (", ".join(TEST_STYLES), derive["tests"])))
    for mode in ("capture", "count"):
        if mode in derive:
            try:
                compiled = re.compile(derive[mode])
            except (re.error, TypeError) as exc:
                findings.append(Finding(
                    "schema", claim_id,
                    "`derive.%s` is not a regex: %s" % (mode, exc)))
                continue
            if mode == "capture" and compiled.groups != 1:
                findings.append(Finding(
                    "schema", claim_id,
                    "`derive.capture` needs exactly one group, the number"))
    if "format" not in claim:
        findings.append(Finding(
            "schema", claim_id,
            "a derived claim needs `format`, to say how the number is written"))
    if "raw" in claim:
        findings.append(Finding(
            "schema", claim_id,
            "a derived claim has no `raw`: the source is the number, and a "
            "second copy of it here is what drifts"))
    return findings


def find_project(root, name):
    """`name` inside `root` or beside it, matched case-insensitively."""
    root = pathlib.Path(root).resolve()
    for base in (root, root.parent):
        exact = base / name
        if exact.is_dir():
            return exact
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and child.name.lower() == name.lower():
                    return child
    return None


#: How `derive.tests` can count. "python" is unittest's loader: test methods on
#: classes. "pytest" is pytest's default collection, which unittest's rule
#: undercounts badly - most pytest suites are module-level functions.
TEST_STYLES = ("python", "pytest")


class NotStatic(Exception):
    """A count that cannot be read without running the code."""


def _parametrize_cases(function):
    """How many cases stacked `@pytest.mark.parametrize` decorators make.

    Counted only over a literal list or tuple. Anything else - a variable, a
    call, a comprehension - raises NotStatic, because guessing a count is the
    failure this tool exists to prevent.
    """
    cases = 1
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        name = target.attr if isinstance(target, ast.Attribute) else \
            getattr(target, "id", "")
        if name != "parametrize":
            continue
        values = decorator.args[1] if len(decorator.args) > 1 else next(
            (k.value for k in decorator.keywords if k.arg == "argvalues"), None)
        if not isinstance(values, (ast.List, ast.Tuple)):
            raise NotStatic(
                "%s is parametrized over something that is not a literal list, "
                "so its count cannot be read without running pytest"
                % function.name)
        cases *= len(values.elts)
    return cases


def _is_testcase(node):
    return any((getattr(base, "attr", None) or getattr(base, "id", "")
                ).endswith("TestCase") for base in node.bases)


def _pytest_class_tests(node, outer_cases=1):
    """Tests pytest collects from one class, and from classes nested in it."""
    methods = [item for item in node.body
               if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if _is_testcase(node):
        # unittest classes are collected by any name; parametrize does not
        # apply to them.
        return len([m for m in methods if m.name.startswith("test")])
    if not node.name.startswith("Test") or any(m.name == "__init__"
                                                for m in methods):
        return 0   # pytest skips a Test class with a constructor
    cases = outer_cases * _parametrize_cases(node)
    total = sum(cases * _parametrize_cases(m) for m in methods
                if m.name.startswith("test"))
    for item in node.body:
        if isinstance(item, ast.ClassDef):
            total += _pytest_class_tests(item, cases)
    return total


def count_pytest_tests(text):
    """Tests pytest's default collection finds in one file, parametrize included.

    Module-level `test*` functions, `test*` methods on `Test*` classes that
    have no `__init__` (nested ones too), and every `test*` method of a
    `unittest.TestCase` subclass. Parametrized fixtures and custom collection
    hooks are not seen; a suite that uses them should count with
    `pytest --collect-only` and anchor the claim with `evidence` instead.
    """
    tree = ast.parse(text)
    total = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            total += _parametrize_cases(node)
        elif isinstance(node, ast.ClassDef):
            total += _pytest_class_tests(node)
    return total


def count_python_tests(text):
    """Test methods defined on classes, the way unittest's loader names them.

    Parsed rather than grepped: a string holding a test file is not tests.
    """
    tree = ast.parse(text)
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name.startswith("test"):
                    total += 1
    return total


class NotDerived(Exception):
    """A number could not be read. `fatal` is False only for a project that is
    not checked out here - a gap in what this run can see, not evidence that
    the claim is wrong."""

    def __init__(self, message, fatal=True):
        Exception.__init__(self, message)
        self.fatal = fatal


def derive_number(root, derive):
    """Read a claim's number out of files, or raise NotDerived saying why."""
    base = pathlib.Path(root)
    if derive.get("project"):
        found = find_project(root, derive["project"])
        if found is None:
            raise NotDerived("NOT CHECKED: project %r is not checked out "
                             "beside or inside %s"
                             % (derive["project"], base.resolve()),
                             fatal=False)
        base = found
    paths = []
    for pattern in derive["files"]:
        paths.extend(p for p in base.glob(pattern) if p.is_file())
    paths = sorted(set(paths))
    if not paths:
        raise NotDerived("%s matches no files; a source that moved must not "
                         "read as zero" % ", ".join(derive["files"]))
    texts = []
    for path in paths:
        with io.open(str(path), encoding="utf-8", errors="replace") as handle:
            texts.append((path, handle.read()))

    if "tests" in derive:
        counter = count_pytest_tests if derive["tests"] == "pytest" \
            else count_python_tests
        total = 0
        for path, text in texts:
            try:
                total += counter(text)
            except SyntaxError as exc:
                raise NotDerived("%s does not parse: %s" % (path.name, exc))
            except NotStatic as exc:
                raise NotDerived("%s: %s" % (path.name, exc))
        return total
    if "count" in derive:
        pattern = re.compile(derive["count"], re.MULTILINE)
        return sum(len(pattern.findall(text)) for _p, text in texts)
    pattern = re.compile(derive["capture"], re.MULTILINE)
    hits = [m.group(1) for _p, text in texts for m in pattern.finditer(text)]
    if len(hits) != 1:
        raise NotDerived("`capture` must match exactly once and matched %d "
                         "times" % len(hits))
    # A number when it is one; otherwise the text as captured, so a version
    # like "0.1.1" or "3.8" can be pinned with a `%s` format. A numeric format
    # given text fails at rendering and says so.
    for kind in (int, float):
        try:
            return kind(hits[0])
        except ValueError:
            pass
    return hits[0]


def apply_format(fmt, value):
    """`fmt % value`, or `fmt.format(value)` when fmt uses `{}` fields.

    Both, because `%` cannot write a thousands separator and a README very
    often does: "37,583 respondents" needs `{:,} respondents`.
    """
    if "{" in fmt:
        return fmt.format(value)
    return fmt % value


def _scaled(value, scale):
    """Scale a number; leave text alone rather than repeating it."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value * scale
    return value


def check_derived(claims, root):
    """The number read from the project's own files still renders as `value`."""
    findings = []
    for claim in claims:
        claim_id = claim.get("id", "?")
        derive = claim.get("derive")
        if derive is None or _check_derive_spec(claim_id, claim, derive):
            continue   # the schema check has already said what is wrong
        try:
            number = derive_number(root, derive)
        except NotDerived as exc:
            findings.append(Finding("derived", claim_id, str(exc),
                                    fatal=exc.fatal))
            continue
        try:
            rendered = apply_format(claim["format"],
                                    _scaled(number, claim.get("scale", 1)))
        except (TypeError, ValueError, IndexError, KeyError) as exc:
            findings.append(Finding(
                "derived", claim_id, "format %r cannot render %r: %s"
                % (claim["format"], number, exc)))
            continue
        if rendered != claim["value"]:
            findings.append(Finding(
                "derived", claim_id,
                "the source now says %r; the ledger publishes %r"
                % (rendered, claim["value"])))
    return findings


def rendered_value(claim):
    """`format % (raw * scale)` — what the ledger's own number looks like.

    `scale` exists because `raw` has to stay exactly what the engine returns,
    so that `check_computed` can compare the two without either side knowing
    how the other is written. An engine commonly returns a proportion while
    the README publishes a percentage. One of those has to move, and it
    must not be `raw`: the moment the ledger stores a display-scaled number,
    the comparison against the engine needs the scale applied in the project's
    own test, which is the code this is trying to stop every project writing.
    """
    return apply_format(claim["format"],
                        _scaled(claim["raw"], claim.get("scale", 1)))


def check_rounding(claims):
    """`format % (raw * scale)` still renders `value`.

    A number rounding differently is a different published claim, so this is a
    failure and not a tolerance: a formatting change is a real change to a
    published claim.
    """
    findings = []
    for claim in claims:
        if "raw" not in claim or "format" not in claim:
            continue
        claim_id = claim.get("id", "?")
        try:
            rendered = rendered_value(claim)
        except (TypeError, ValueError, IndexError, KeyError) as exc:
            findings.append(Finding(
                "rounding", claim_id,
                "format %r cannot render raw %r: %s"
                % (claim["format"], claim["raw"], exc)))
            continue
        if rendered != claim["value"]:
            findings.append(Finding(
                "rounding", claim_id,
                "raw %r renders as %r through %r, but the ledger publishes %r"
                % (claim["raw"], rendered, claim["format"], claim["value"])))
    return findings


def check_prose(claims, root):
    """Presence and contradiction, over the files each claim names."""
    root = pathlib.Path(root)
    findings = []
    cache = {}

    def text_of(relative):
        if relative not in cache:
            target = root / relative
            if not target.exists():
                cache[relative] = None
            else:
                with io.open(str(target), encoding="utf-8",
                             errors="replace") as handle:
                    cache[relative] = normalise(handle.read())
        return cache[relative]

    for claim in claims:
        claim_id = claim.get("id", "?")
        value = claim.get("value")
        paths = claim.get("appears_in") or []
        if not value:
            continue
        if not paths:
            findings.append(Finding(
                "unpublished", claim_id,
                "no `appears_in`; the ledger holds this number but nothing "
                "says it is written down anywhere", fatal=False))
            continue

        forms = written_forms(claim)
        shapes = [shape_of(form) for form in forms]
        near = claim.get("near") or []
        width = claim.get("window") or DEFAULT_WINDOW
        fired = set()

        for relative in paths:
            text = text_of(relative)
            if text is None:
                findings.append(Finding(
                    "presence", claim_id, "file does not exist",
                    path=relative))
                continue
            if not any(form in text for form in forms):
                findings.append(Finding(
                    "presence", claim_id,
                    "does not contain %s"
                    % " or ".join(repr(f) for f in forms), path=relative))
                continue

            if not near:
                findings.append(Finding(
                    "contradiction", claim_id,
                    "NOT CHECKED: no `near` phrases, so a different number of "
                    "the same shape elsewhere in this file would not be seen",
                    path=relative, fatal=False))
                continue

            spans = windows(text, near, width)
            if not spans:
                findings.append(Finding(
                    "contradiction", claim_id,
                    "NOT CHECKED: none of the `near` phrases (%s) appear here, "
                    "so there was no window to scan"
                    % ", ".join(repr(p) for p in near),
                    path=relative, fatal=False))
                continue

            allow = claim.get("allow") or {}
            wrong = []
            for start, end in spans:
                for shape in shapes:
                    for match in shape.finditer(text, start, end):
                        found = match.group(0)
                        if found in forms:
                            continue
                        if found in allow:
                            fired.add(found)
                            continue
                        wrong.append((found, excerpt(text, match.start(),
                                                     match.end())))
            for found, context in sorted(set(wrong)):
                findings.append(Finding(
                    "contradiction", claim_id,
                    "the ledger publishes %r and %r sits beside it: %s"
                    % (value, found, context), path=relative))
            # `near` is matched case-insensitively and the forms are not, so a
            # window can open on a phrase whose number is written a way this
            # claim does not declare. Saying nothing would be a pass.
            if not any(form in text[s:e] for s, e in spans for form in forms):
                findings.append(Finding(
                    "contradiction", claim_id,
                    "the `near` phrases open a window here that contains none "
                    "of %s, so the scan looked somewhere the claim is not"
                    % " or ".join(repr(f) for f in forms),
                    path=relative, fatal=False))

        for excused in sorted(set(claim.get("allow") or {}) - fired):
            findings.append(Finding(
                "allow", claim_id,
                "excuses %r and nothing in %s matches it any more; an "
                "exemption whose reason has gone stale gets copied forward"
                % (excused, " or ".join(paths)), fatal=False))
    return findings


def check_evidence(claims, root):
    """The line a claim was read off is still in the file it was read from.

    Not every number a project publishes can be recomputed on demand. Some come
    from a one-shot analysis over a warm cache that is too large to commit, and
    what the repository keeps is the run's transcript. That is a weaker anchor
    than code — it proves the number was produced, not that it is right — and
    weaker is not the same as absent. A transcript in version control is
    checkable, deterministic, and needs no network.

    So this is deliberately provenance and not verification, and the difference
    is written into the finding rather than left for a reader to assume.
    """
    root = pathlib.Path(root)
    findings = []
    for claim in claims:
        evidence = claim.get("evidence")
        if not isinstance(evidence, dict):
            continue
        claim_id = claim.get("id", "?")
        relative = evidence.get("file")
        wanted = evidence.get("line")
        if not relative or not wanted:
            continue
        target = root / relative
        if not target.exists():
            findings.append(Finding(
                "evidence", claim_id,
                "the file this number was read off is gone", path=relative))
            continue
        with io.open(str(target), encoding="utf-8",
                     errors="replace") as handle:
            text = normalise(handle.read())
        if normalise(wanted) not in text:
            findings.append(Finding(
                "evidence", claim_id,
                "no longer contains the line this number was read off: %r"
                % wanted, path=relative))
    return findings


def check_coverage(claims, root, patterns, exempt=None):
    """Files that quote a claim and are not pinned to it.

    A check that starts from what is written down cannot see what was never
    written down. A README listed in `appears_in` is guarded; the public page
    that quotes the same number and was never listed is not, and no amount of
    checking the README finds it.
    """
    root = pathlib.Path(root)
    findings = []
    candidates = []
    for pattern in patterns:
        candidates.extend(root.glob(pattern))

    for claim in claims:
        value = claim.get("value")
        if not value:
            continue
        claim_id = claim.get("id", "?")
        forms = written_forms(claim)
        pinned = set(claim.get("appears_in") or [])
        for target in sorted(set(candidates)):
            if not target.is_file():
                continue
            relative = target.relative_to(root).as_posix()
            if relative in pinned or relative in (exempt or {}):
                continue
            try:
                with io.open(str(target), encoding="utf-8",
                             errors="replace") as handle:
                    text = normalise(handle.read())
            except OSError:
                continue
            hit = next((form for form in forms if form in text), None)
            if hit:
                findings.append(Finding(
                    "coverage", claim_id,
                    "quotes %r and is not in `appears_in`, so nothing checks "
                    "it" % hit, path=relative))
    return findings


def verify(root, ledger_path=None, scan=None):
    """Every check, against one project directory. Returns a list of Findings."""
    root = pathlib.Path(root)
    path = ledger_path or root / "claims.json"
    claims = load(path)
    meta = load_meta(path)
    findings = check_schema(claims)
    findings.extend(check_exemptions(meta, root))
    findings.extend(check_rounding(claims))
    findings.extend(check_evidence(claims, root))
    findings.extend(check_derived(claims, root))
    findings.extend(check_prose(claims, root))
    if scan:
        findings.extend(check_coverage(claims, root, scan,
                                       meta.get("exempt")))
    return claims, findings


def check_computed(claims, computed, default_places=12):
    """The one link a project has to close with its own code.

    `computed` maps a claim id to what the engine returns today. A claim with
    no `raw` is not checkable this way and is reported as such rather than
    passed over, because a silent skip here would leave the whole chain
    looking green while its first link was never tested — which is how the
    a trailing `# python:` comment came to be the only record of a real
    project's computed value.
    """
    findings = []
    by_id = {}
    for claim in claims:
        if claim.get("id"):
            by_id[claim["id"]] = claim

    for claim_id in sorted(computed):
        if claim_id not in by_id:
            findings.append(Finding(
                "computed", claim_id,
                "the engine produced this and the ledger has no such claim"))
    for claim_id, claim in sorted(by_id.items()):
        if "raw" not in claim:
            continue
        if claim_id not in computed:
            findings.append(Finding(
                "computed", claim_id,
                "has a `raw` value and nothing recomputed it", fatal=False))
            continue
        got = computed[claim_id]
        want = claim["raw"]
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            tolerance = claim.get("tolerance")
            if tolerance is None:
                tolerance = 10.0 ** -default_places
            if abs(got - want) > tolerance:
                findings.append(Finding(
                    "computed", claim_id,
                    "engine returns %r; the ledger records %r (tolerance %g)"
                    % (got, want, tolerance)))
        elif got != want:
            findings.append(Finding(
                "computed", claim_id,
                "engine returns %r; the ledger records %r" % (got, want)))
    return findings


def stale(claims, asof=None, source=None):
    """Claims past their own re-check horizon. `source` labels the project."""
    asof = asof or datetime.date.today()
    out = []
    for claim in claims:
        horizon = claim.get("recheck_by")
        if not horizon:
            continue
        try:
            when = datetime.date.fromisoformat(horizon)
        except (TypeError, ValueError):
            continue
        if when < asof:
            out.append((source, claim, (asof - when).days))
    return out


def render(claims, fmt="md"):
    """The grade block a project puts next to its own numbers."""
    rows = []
    for claim in claims:
        rows.append((claim.get("value", ""), claim.get("claim", ""),
                     claim.get("status", ""), claim.get("anchor", ""),
                     claim.get("checked_on", "")))
    if fmt == "md":
        lines = ["| Value | Claim | Status | Anchor | Checked |",
                 "| --- | --- | --- | --- | --- |"]
        for row in rows:
            lines.append("| %s | %s | %s | %s | %s |"
                         % tuple(str(cell).replace("|", "\\|") for cell in row))
        return "\n".join(lines)
    if fmt == "html":
        def esc(cell):
            return (str(cell).replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;"))
        lines = ['<table class="claims">',
                 "<thead><tr><th>Value</th><th>Claim</th><th>Status</th>"
                 "<th>Anchor</th><th>Checked</th></tr></thead>", "<tbody>"]
        for row in rows:
            lines.append("<tr>%s</tr>" % "".join(
                '<td class="claim-%s">%s</td>' % (
                    "status" if index == 2 else "cell", esc(cell))
                for index, cell in enumerate(row)))
        lines.extend(["</tbody>", "</table>"])
        return "\n".join(lines)
    raise ValueError("unknown format %r" % fmt)


def _report(findings, quiet=False):
    fatal = [f for f in findings if f.fatal]
    notes = [f for f in findings if not f.fatal]
    for finding in fatal:
        print(finding.line())
    if not quiet:
        for finding in notes:
            print(finding.line())
    return fatal, notes


# ---------------------------------------------------------------------------
# suggest: draft a ledger from prose that has none.
#
# Claims are declared, not discovered, and this does not change that. It finds
# candidates and writes DRAFTS, every one carrying a `todo` that `verify`
# reports as a failure until a person has read the claim and deleted the line.
# A drafting tool whose output passed unreviewed would be the discovery flood
# this tool refuses to be, with extra steps.

#: A number, optionally with thousands separators or decimals, optionally with
#: a %/x suffix, optionally followed by one lowercase word - the unit that
#: makes "138 tests" a claim and a bare "138" usually not one.
CANDIDATE = re.compile(
    r"(?<![\w.,/#$-])"
    r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(?![.,]\d)"
    # The suffix before the word-boundary check: "2.5x" is a multiplier, and
    # checking for a following letter first rejected every one of them.
    r"(%|×|x)?(?![\w-])"
    r"(?:[ \t]+([a-z][a-z-]{1,}))?")

#: Words after a number that are grammar, not a unit.
NOT_UNITS = frozenset("""a an and are as at be but by for from if in into is it
of on or so than that the then this to was were which with""".split())

#: Stripped before scanning: addresses, link targets and inline code, where a
#: digit is an identifier rather than a claim.
NOT_PROSE = re.compile(r"https?://\S+|\]\([^)]*\)|`[^`\n]*`")
LIST_ITEM = re.compile(r"^\s*\d+[.)]\s")
SOURCE_SUFFIXES = (".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".kt",
                   ".toml", ".cfg", ".ini", ".yaml", ".yml", ".json", ".gd")
SKIP_DIRS = frozenset((".git", "node_modules", ".venv", "venv", "__pycache__",
                       "build", "dist", ".tox", ".mypy_cache"))


def _is_unit(word, digits, suffix):
    """Whether the word after a number names what is counted.

    A percentage or a multiplier describes itself, so it takes no unit ("15%
    against" is a sentence, not a claim). Otherwise a unit is nearly always a
    plural noun: "27 routes", "160 currencies". Requiring the plural, except
    after 1, removes the verbs and adjectives that follow a number far more
    often than units do - "150 have", "20 positioned", "18 real" - measured on
    a real README, where they were most of the noise.
    """
    if suffix or word in NOT_UNITS or word.endswith(("ed", "ly", "ing")):
        return False
    return word.endswith("s") or digits == "1"


def find_candidates(text):
    """(line, value, number, unit) for each number in prose that reads like a claim."""
    out = []
    fenced = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            # Inside a code block a number is usually output or code. Only a
            # comment is prose - "# 138 tests" beside a test command is a claim.
            if "#" not in line:
                continue
            line = line.split("#", 1)[1]
        if LIST_ITEM.match(line):
            line = LIST_ITEM.sub(" ", line, count=1)
        line = NOT_PROSE.sub(" ", line)
        for match in CANDIDATE.finditer(line):
            digits, suffix, unit = match.groups()
            if unit is not None and not _is_unit(unit, digits, suffix):
                unit = None
            if not suffix and not unit:
                continue          # a bare number: usually not a claim
            number = float(digits.replace(",", "")) if "." in digits \
                else int(digits.replace(",", ""))
            if isinstance(number, int) and 1900 <= number <= 2099 \
                    and "," not in digits:
                continue          # a year
            value = digits + (suffix or "") + (" " + unit if unit else "")
            out.append((lineno, value, number, unit))
    return out


def _source_files(root):
    for path in sorted(pathlib.Path(root).rglob("*")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in SOURCE_SUFFIXES \
                and path.stat().st_size < 1000000:
            yield path


def _python_test_globs(root):
    root = pathlib.Path(root)
    return [g for g in ("tests/**/test_*.py", "tests/**/*_test.py",
                        "test/**/test_*.py", "test_*.py")
            if any(p.is_file() for p in root.glob(g))]


def propose_source(root, number, unit):
    """A `derive` that re-derives this exact number, or None.

    Only a proposal that was run and reproduced the number is returned. A
    plausible-looking source that gives a different number is worse than none.
    """
    if not isinstance(number, int):
        return None
    if unit in ("test", "tests"):
        globs = _python_test_globs(root)
        for style in ("pytest", "python"):
            if not globs:
                break
            spec = {"files": globs, "tests": style}
            try:
                if derive_number(root, spec) == number:
                    return spec
            except NotDerived:
                continue
        return None
    constant = re.compile(r"^\s*(?:const\s+|export\s+const\s+)?"
                          r"([A-Z][A-Z0-9_]{2,})\s*(?::\s*\w+\s*)?[:=]=?\s*"
                          r"%d\s*[,;]?\s*(?:#.*|//.*)?$" % number, re.MULTILINE)
    for path in _source_files(root):
        try:
            with io.open(str(path), encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for match in constant.finditer(text):
            name = match.group(1)
            relative = path.relative_to(root).as_posix()
            spec = {"files": [relative],
                    "capture": r"^\s*(?:const\s+|export\s+const\s+)?%s\s*"
                               r"(?::\s*\w+\s*)?[:=]=?\s*(\d+)" % re.escape(name)}
            try:
                if derive_number(root, spec) == number:
                    return spec
            except NotDerived:
                continue      # the name is assigned twice: ambiguous, skip it
    return None


def _format_for(value, number):
    """A format that renders `number` back into exactly `value`."""
    digits = re.match(r"[\d,.]+", value).group(0)
    rest = value[len(digits):].replace("%", "%%")
    if "," in digits:
        return "{:,}" + value[len(digits):].replace("{", "{{").replace("}", "}}")
    if isinstance(number, float):
        return "%%.%df" % len(digits.split(".")[1]) + rest
    return "%d" + rest


def _slug(unit, taken):
    base = re.sub(r"[^a-z0-9]+", "_", (unit or "figure").lower()).strip("_")
    base = base or "figure"
    slug, n = base, 2
    while slug in taken:
        slug, n = "%s_%d" % (base, n), n + 1
    taken.add(slug)
    return slug


def suggest(root, files, ledger=None, today=None):
    """(draft claims, report lines). Nothing is written by this function."""
    root = pathlib.Path(root)
    today = (today or datetime.date.today()).isoformat()
    existing = []
    if ledger is not None and pathlib.Path(ledger).exists():
        existing = load(ledger)
    taken = set(c.get("id") for c in existing)
    drafts, report = [], []
    for relative in files:
        path = root / relative
        if not path.is_file():
            report.append("skip  %s: not a file" % relative)
            continue
        with io.open(str(path), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        pinned = set(c.get("value") for c in existing
                     if relative in (c.get("appears_in") or []))
        seen = set()
        for lineno, value, number, unit in find_candidates(text):
            where = "%s:%d" % (relative, lineno)
            # Contained in a pinned value, on number boundaries: "293 tests"
            # inside "293 tests over 6 files", but never "3 tests" inside
            # "138 tests".
            inside = re.compile(r"(?<![\d.,])%s(?![\d])" % re.escape(value))
            if any(inside.search(done) for done in pinned):
                report.append("pinned  %-24s %s" % (where, value))
                continue
            if value in seen:
                continue
            seen.add(value)
            claim = {
                "id": _slug(unit, taken),
                "claim": "TODO: what this number is",
                "value": value,
                "status": "unconfirmed",
                "anchor": "TODO: where a reader goes to check it",
                "checked_on": today,
                "appears_in": [relative],
            }
            if unit:
                claim["near"] = [unit]
            source = propose_source(root, number, unit)
            if source:
                claim["format"] = _format_for(value, number)
                claim["derive"] = source
                claim["status"] = "measured"
                claim["durable"] = "read from source on every verify"
                claim["todo"] = ("found a source that reproduces %s - confirm "
                                 "it is the right one, fill in claim and "
                                 "anchor, then delete this line" % value)
                report.append("source  %-24s %s  <- %s" % (
                    where, value, source["files"][0]))
            else:
                claim["todo"] = ("no source found - add derive, raw with "
                                 "format, or evidence; fill in claim, anchor "
                                 "and recheck_by; or delete this claim if "
                                 "the number is not one")
                report.append("draft   %-24s %s" % (where, value))
            drafts.append(claim)
    return drafts, report


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="docclaims",
        description="Check the numbers a repository publishes against their sources.")
    parser.add_argument("--version", action="version",
                        version="docclaims " + __version__)
    sub = parser.add_subparsers(dest="command")

    verify_cmd = sub.add_parser("verify", help="every check, one project")
    verify_cmd.add_argument("project")
    verify_cmd.add_argument("--ledger", default=None)
    verify_cmd.add_argument("--scan", nargs="+", default=None,
                            help="globs to sweep for unpinned occurrences")
    verify_cmd.add_argument("--json", default=None)
    verify_cmd.add_argument("--quiet", action="store_true",
                            help="failures only; notes are suppressed")

    stale_cmd = sub.add_parser("stale", help="claims past their horizon")
    stale_cmd.add_argument("projects", nargs="+")
    stale_cmd.add_argument("--asof", default=None)
    stale_cmd.add_argument("--ledger", default="claims.json")

    suggest_cmd = sub.add_parser(
        "suggest", help="draft claims for the numbers in a file, for review")
    suggest_cmd.add_argument("files", nargs="*", default=["README.md"])
    suggest_cmd.add_argument("--root", default=".")
    suggest_cmd.add_argument("--ledger", default=None,
                             help="existing ledger; its pinned values are skipped")
    suggest_cmd.add_argument("--out", default=None,
                             help="write drafts here instead of stdout")

    render_cmd = sub.add_parser("render", help="the grade block")
    render_cmd.add_argument("project")
    render_cmd.add_argument("--ledger", default=None)
    render_cmd.add_argument("--format", default="md", choices=("md", "html"))

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    if args.command == "verify":
        root = pathlib.Path(args.project)
        try:
            claims, findings = verify(root, args.ledger, args.scan)
        except LedgerError as exc:
            print("FAIL  ledger         %s" % exc)
            return 1
        if not args.scan:
            # A finding rather than a printed hint, so it is counted in the
            # summary and carried into --json like every other NOT CHECKED.
            findings.append(Finding(
                "coverage", "-", "NOT CHECKED: pass --scan to sweep for files "
                "that quote a claim and are not pinned to it", fatal=False))
        fatal, notes = _report(findings, args.quiet)
        if args.json:
            with io.open(args.json, "w", encoding="utf-8") as handle:
                json.dump({"project": str(root), "claims": len(claims),
                           "findings": [f.as_dict() for f in findings]},
                          handle, indent=2)
        # How a number is anchored is worth printing every run. A ledger that
        # slid from recomputable to transcript-only would otherwise look
        # identical from here, and that slide is a real weakening.
        recomputable = len([c for c in claims if "raw" in c])
        traced = len([c for c in claims if c.get("evidence")])
        derived = len([c for c in claims if c.get("derive")])
        print("%d claims: %d recomputable, %d read from source, %d anchored "
              "to a transcript" % (len(claims), recomputable, derived, traced))
        print("%d failures, %d notes" % (len(fatal), len(notes)))
        return 1 if fatal else 0

    if args.command == "stale":
        asof = (datetime.date.fromisoformat(args.asof) if args.asof
                else datetime.date.today())
        rows = []
        failed = False
        for project in args.projects:
            path = pathlib.Path(project)
            try:
                claims = load(path / args.ledger)
            except LedgerError as exc:
                print("FAIL  ledger         %s" % exc)
                failed = True
                continue
            rows.extend(stale(claims, asof, source=path.name))
        for source, claim, days in sorted(rows, key=lambda r: -r[2]):
            print("STALE %-12s %-24s %s days past %s  (%s)"
                  % (source, claim.get("id", "?"), days,
                     claim.get("recheck_by"), claim.get("claim", "")))
        print("%d claims past their horizon as of %s" % (len(rows), asof))
        return 1 if (rows or failed) else 0

    if args.command == "suggest":
        root = pathlib.Path(args.root)
        ledger = pathlib.Path(args.ledger) if args.ledger else root / "claims.json"
        try:
            drafts, report = suggest(root, args.files, ledger)
        except LedgerError as exc:
            print("FAIL  ledger         %s" % exc)
            return 1
        document = json.dumps({"claims": drafts}, indent=2, ensure_ascii=False)
        if args.out:
            target = pathlib.Path(args.out)
            if target.exists():
                # Drafts written over a reviewed ledger would erase the review.
                print("FAIL  %s exists; drafts are never written over a "
                      "ledger - pass a new path and merge by hand" % target)
                return 1
            with io.open(str(target), "w", encoding="utf-8") as handle:
                handle.write(document + "\n")
        for line in report:
            print(line, file=sys.stderr if not args.out else sys.stdout)
        if not args.out:
            print(document)
        found = len([d for d in drafts if "derive" in d])
        print("%d drafts, %d with a source that reproduces the number; every "
              "draft fails verify until its todo is deleted"
              % (len(drafts), found), file=sys.stderr if not args.out else sys.stdout)
        return 0

    if args.command == "render":
        root = pathlib.Path(args.project)
        try:
            claims = load(args.ledger or root / "claims.json")
        except LedgerError as exc:
            print("FAIL  ledger         %s" % exc)
            return 1
        print(render(claims, args.format))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
