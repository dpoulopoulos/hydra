"""Check that every Google-style ``Args:`` section in ``app`` describes the signature above it.

Neither ruff nor mypy reads a docstring's parameter list: ruff's pydocstyle rules stop at the shape of the
section and mypy ignores docstrings entirely. A parameter can therefore be renamed or dropped and leave a
docstring behind that documents something the function never accepted, which is what happened to
``generate_new_account_email``. This module walks the source tree and closes that gap for every function at
once, rather than for the handful a past bug happened to touch.

The source is read with ``ast`` instead of ``inspect`` so that nothing has to be imported: functions hidden
behind decorators keep the signature they were written with, private helpers are covered too, and a module
with import-time side effects cannot skew the result.

A function that takes parameters and carries a docstring has to describe them: leaving the section out is as
much a way to lose the description as letting it drift, and was caught by the email-only guard this module
replaces. A function written without a docstring at all is a separate matter, and is left to ruff.
"""

import ast
import re
from pathlib import Path

import pytest

# The package under inspection, resolved from this file so the walk does not depend on the working directory.
SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "app"

# Alembic revisions are generated, and are excluded from ruff and mypy for the same reason.
EXCLUDED_DIRS = frozenset({"alembic"})

# Parameters that belong to the binding of a method rather than to its interface, and are never documented.
IMPLICIT_PARAMETERS = frozenset({"self", "cls"})

# A parameter entry in an ``Args:`` section: a name, an optional type in parentheses, then a colon.
ARG_ENTRY = re.compile(r"\*{0,2}(?P<name>\w+)\s*(\([^)]*\))?\s*:")

FunctionDef = ast.FunctionDef | ast.AsyncFunctionDef


def _indentation(line: str) -> int:
    """Count the leading whitespace of a line."""
    return len(line) - len(line.lstrip())


def _source_files() -> list[Path]:
    """Collect the modules of the application package."""
    return sorted(
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if EXCLUDED_DIRS.isdisjoint(path.relative_to(SOURCE_ROOT).parent.parts)
    )


def _functions(path: Path) -> list[tuple[str, FunctionDef]]:
    """Collect every function in a module, qualified by the classes and functions enclosing it."""
    found: list[tuple[str, FunctionDef]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualified_name = f"{prefix}{child.name}"
                found.append((qualified_name, child))
                walk(child, f"{qualified_name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), "")
    return found


def _documented_parameters(docstring: str) -> list[str] | None:
    """Collect the parameter names of a Google-style ``Args:`` section, or None when there is no such section.

    Only the entries at the outermost indentation of the section are names: anything deeper continues the
    description of the entry above it, and the section ends at the first line indented no further than the
    ``Args:`` header. That indentation is read off the first line of the section rather than assumed to be
    four spaces, so a section indented by some other amount is still checked instead of quietly parsing as
    an empty one.
    """
    lines = docstring.splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip() == "Args:"), None)
    if header_index is None:
        return None

    header_indent = _indentation(lines[header_index])
    entry_indent = None

    names = []
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        indent = _indentation(line)
        if indent <= header_indent:
            break
        if entry_indent is None:
            entry_indent = indent
        if indent == entry_indent and (match := ARG_ENTRY.match(line.strip())):
            names.append(match.group("name"))
    return names


def _signature_parameters(function: FunctionDef) -> list[str]:
    """Collect the parameter names a function accepts, in the order they are written."""
    arguments = function.args
    names = [argument.arg for argument in arguments.posonlyargs + arguments.args]
    if arguments.vararg:
        names.append(arguments.vararg.arg)
    names += [argument.arg for argument in arguments.kwonlyargs]
    if arguments.kwarg:
        names.append(arguments.kwarg.arg)
    return [name for name in names if name not in IMPLICIT_PARAMETERS]


def _documented_functions() -> list[tuple[str, list[str] | None, list[str]]]:
    """Collect every function whose docstring has to describe a signature, with the two lists to compare.

    A function is in scope when it carries a docstring and either opens an ``Args:`` section or takes
    parameters. The documented list is None when there is no section, which is a failure of its own for a
    function that takes something, rather than a case the walk passes over.
    """
    documented = []
    for path in _source_files():
        for qualified_name, function in _functions(path):
            docstring = ast.get_docstring(function)
            if not docstring:
                continue
            parameters = _documented_parameters(docstring)
            accepted = _signature_parameters(function)
            if parameters is None and not accepted:
                continue
            location = f"{path.relative_to(SOURCE_ROOT)}:{function.lineno}:{qualified_name}"
            documented.append((location, parameters, accepted))
    return documented


DOCUMENTED_FUNCTIONS = _documented_functions()


class TestDocstringsMatchSignatures:
    """Test that documented parameters match the signatures they describe."""

    def test_source_tree_is_walked(self) -> None:
        """The walk finds the documented functions of the package."""
        # Assert: Verify a mistyped root or a broken parser fails here rather than passing silently
        assert len(_source_files()) > 50
        assert len(DOCUMENTED_FUNCTIONS) > 100

    @pytest.mark.parametrize(
        ("documented", "accepted"),
        [pytest.param(documented, accepted, id=location) for location, documented, accepted in DOCUMENTED_FUNCTIONS],
    )
    def test_documented_args_match_signature(self, documented: list[str] | None, accepted: list[str]) -> None:
        """Every function documents exactly the parameters it accepts, in the order it accepts them."""
        # Assert: Verify a docstring on a function that takes something says what it takes, so dropping the
        # section is as loud as letting it drift
        assert documented is not None, f"docstring has no Args: section for {', '.join(accepted)}"

        # Assert: Verify the section holds entries at all, so one this parser cannot read fails here instead
        # of passing as an empty list against a signature that takes nothing
        assert documented, "Args: section has no readable parameter entries"

        # Assert: Verify the docstring describes this signature and no other
        assert documented == accepted
