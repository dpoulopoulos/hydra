"""Check that every Google-style docstring in ``app`` describes the function above it.

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

``Returns:`` is checked for presence rather than content: the prose describing a value cannot be compared to
the value, but whether a function produces one at all is exactly what the return annotation says, so a
section that outlives the value it describes - or goes missing when a helper starts returning something -
still fails here.

``Raises:`` is checked in one direction: every exception raised in the body has to be listed, but a listed
exception does not have to be raised there. Most of the exceptions a service documents are raised for it by
a repository or a helper it calls, and finding those would mean following every callee through the package
and back out of its dependencies. Listing more than the body raises is therefore how the convention is
meant to be used, and only the half that is decidable from one function is enforced.
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

# An entry in a Google-style section: a name, an optional type in parentheses, then a colon. The name may
# carry stars, for the variadic parameters of an ``Args:`` section, or dots, for an exception a ``Raises:``
# section reaches through its module.
SECTION_ENTRY = re.compile(r"\*{0,2}(?P<name>[\w.]+)\s*(\([^)]*\))?\s*:")

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


def _has_section(docstring: str, header: str) -> bool:
    """Whether a docstring opens the named Google-style section."""
    return any(line.strip() == f"{header}:" for line in docstring.splitlines())


def _returns_a_value(function: FunctionDef) -> bool:
    """Whether the return annotation of a function promises a value worth describing.

    An unannotated function is taken to return nothing: mypy runs over this package in strict mode, so the
    only signatures it leaves unannotated are the ``__init__`` methods that cannot return anything anyway.
    """
    return function.returns is not None and ast.unparse(function.returns) != "None"


def _yields(function: FunctionDef) -> bool:
    """Whether a function is a generator, and so describes what it produces under ``Yields:``."""
    found = False

    def walk(node: ast.AST) -> None:
        nonlocal found
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
                continue
            if isinstance(child, ast.Yield | ast.YieldFrom):
                found = True
            walk(child)

    walk(function)
    return found


def _always_raises(function: FunctionDef) -> bool:
    """Whether a function ends by raising, and so never returns the value its annotation names.

    The refusing implementations of a protocol are written this way: they keep the annotation of the method
    they stand in for so that callers type-check, and describe themselves under ``Raises:`` instead. Asking
    them for a ``Returns:`` section would be asking them to describe a value that is never produced.
    """
    return isinstance(function.body[-1], ast.Raise)


def _bound_names(function: FunctionDef) -> set[str]:
    """Collect the names a function binds itself: its parameters, its assignments and its caught exceptions.

    Args:
        function: The function to walk.

    Returns:
        Every name that refers to a value the body holds rather than to something outside it.
    """
    arguments = function.args
    names = {argument.arg for argument in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _raised_exceptions(function: FunctionDef) -> list[str]:
    """Collect the exception classes a function raises in its own body.

    A bare ``raise`` re-raises whatever is being handled and names no class, and a ``raise`` of a name the
    body binds re-raises an exception built somewhere else - the ``except`` clause that caught it, or the
    variable it was put aside in. Neither says at the raise site what is being raised, so neither is asked
    of the docstring. A name the body does not bind is the class itself, whether it is constructed there or
    raised as it stands.

    Nested functions and classes are skipped: they are walked as functions of their own, and what they
    raise belongs to their own docstrings.

    Args:
        function: The function to walk.

    Returns:
        The names of the exception classes raised directly in the body, sorted and without repeats.
    """
    bound = _bound_names(function)
    names = set()

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
                continue
            if isinstance(child, ast.Raise) and child.exc is not None:
                raised = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if isinstance(raised, ast.Name | ast.Attribute):
                    dotted = ast.unparse(raised)
                    if dotted.partition(".")[0] not in bound:
                        names.add(dotted.rpartition(".")[2])
            walk(child)

    walk(function)
    return sorted(names)


def _section_entries(docstring: str, header: str) -> list[str] | None:
    """Collect the names a Google-style section lists, or None when there is no such section.

    Only the entries at the outermost indentation of the section are names: anything deeper continues the
    description of the entry above it, and the section ends at the first line indented no further than the
    header. That indentation is read off the first line of the section rather than assumed to be four
    spaces, so a section indented by some other amount is still checked instead of quietly parsing as an
    empty one.

    Args:
        docstring: The docstring to read.
        header: The name of the section, written without its colon.

    Returns:
        The names the section lists, or None when the docstring has no such section.
    """
    lines = docstring.splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.strip() == f"{header}:"), None)
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
        if indent == entry_indent and (match := SECTION_ENTRY.match(line.strip())):
            names.append(match.group("name"))
    return names


def _documented_parameters(docstring: str) -> list[str] | None:
    """Collect the parameter names of a Google-style ``Args:`` section.

    Args:
        docstring: The docstring to read.

    Returns:
        The parameters the section names, or None when there is no such section.
    """
    return _section_entries(docstring, "Args")


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


def _returning_functions() -> list[tuple[str, bool, bool]]:
    """Collect every documented function with what it returns and whether it says so.

    A function that only raises is left out: it carries the annotation of the interface it implements
    without ever producing a value under it.
    """
    returning = []
    for path in _source_files():
        for qualified_name, function in _functions(path):
            docstring = ast.get_docstring(function)
            if not docstring or _always_raises(function):
                continue
            # A generator returns an iterator and describes what it produces under Yields:, which is the
            # section the convention asks for and the one the docstrings in this package use.
            header = "Yields" if _yields(function) else "Returns"
            location = f"{path.relative_to(SOURCE_ROOT)}:{function.lineno}:{qualified_name}"
            returning.append((location, _returns_a_value(function), _has_section(docstring, header)))
    return returning


RETURNING_FUNCTIONS = _returning_functions()


def _raising_functions() -> list[tuple[str, list[str], list[str]]]:
    """Collect every documented function that raises, with the exceptions it raises and the ones it names."""
    raising = []
    for path in _source_files():
        for qualified_name, function in _functions(path):
            docstring = ast.get_docstring(function)
            if not docstring:
                continue
            raised = _raised_exceptions(function)
            if not raised:
                continue
            location = f"{path.relative_to(SOURCE_ROOT)}:{function.lineno}:{qualified_name}"
            raising.append((location, raised, _section_entries(docstring, "Raises") or []))
    return raising


RAISING_FUNCTIONS = _raising_functions()


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


class TestDocstringsDescribeReturnValues:
    """Test that a described return value is one the function still produces."""

    def test_source_tree_is_walked(self) -> None:
        """The walk finds the documented functions of the package."""
        # Assert: Verify a mistyped root or a broken parser fails here rather than passing silently
        assert len(RETURNING_FUNCTIONS) > 100

    @pytest.mark.parametrize(
        ("returns_a_value", "documented"),
        [pytest.param(returns, documented, id=location) for location, returns, documented in RETURNING_FUNCTIONS],
    )
    def test_return_section_matches_annotation(self, returns_a_value: bool, documented: bool) -> None:
        """A function describes what it gives back when, and only when, it gives something back."""
        # Assert: Verify a function that produces a value says what it is, so a helper that starts
        # returning one cannot keep a docstring that stops at its arguments
        if returns_a_value:
            assert documented, "docstring has no Returns: or Yields: section for the value it returns"

        # Assert: Verify a description does not outlive the value it describes, which is what happens when
        # a function is changed to return nothing and only its signature is updated
        if not returns_a_value:
            assert not documented, "docstring describes a return value, but the function returns None"


class TestDocstringsDescribeRaisedExceptions:
    """Test that a function names the exceptions it raises."""

    def test_source_tree_is_walked(self) -> None:
        """The walk finds the documented functions that raise."""
        # Assert: Verify a mistyped root or a broken parser fails here rather than passing silently
        assert len(RAISING_FUNCTIONS) > 50

    @pytest.mark.parametrize(
        ("raised", "documented"),
        [pytest.param(raised, documented, id=location) for location, raised, documented in RAISING_FUNCTIONS],
    )
    def test_raised_exceptions_are_documented(self, raised: list[str], documented: list[str]) -> None:
        """Every exception a function raises itself is named in its Raises: section."""
        # Assert: Verify the section a caller reads to decide what to catch names everything the body
        # throws at it, so an exception added to a branch cannot go unmentioned and one renamed out of the
        # body cannot leave its old name behind as the only entry
        undocumented = [exception for exception in raised if exception not in documented]
        assert not undocumented, f"raised but not in Raises: {', '.join(undocumented)}"
