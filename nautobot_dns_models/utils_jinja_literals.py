"""Utilities for extracting and validating literal strings in Jinja templates.

These helpers work at the AST level and do not evaluate templates.
"""

import re
from collections.abc import Iterable

from django.template import engines
from jinja2 import nodes
from jinja2.visitor import NodeVisitor

# Default substring patterns to flag in literal fragments
DEFAULT_LITERAL_PATTERNS = (
    ("..", "Consecutive dots '..' are not allowed"),
    (".-", "Dot followed by hyphen '.-' is not allowed"),
    ("-.", "Hyphen followed by dot '-.' is not allowed"),
)

WHITESPACE_REGEX = re.compile(r"\s")


class LiteralCollector(NodeVisitor):
    """Collect literal strings (TemplateData and Const[str]) from a Jinja AST.

    This visitor walks the parsed Jinja template AST and records:
    - TemplateData segments (free text between tags)
    - Const nodes whose values are strings (string literals inside expressions)

    Collected literals are appended to ``self.literals`` in source order.
    """

    def __init__(self):
        """Initialize the collector with an empty literals list."""
        self.literals = []

    def visit_TemplateData(self, node):  # pylint: disable=invalid-name
        """Handle TemplateData nodes.

        This handles literal text segments such as the '.' between the expressions in:

            {{ obj.name }}.{{ obj.device.name }}

        Args:
            node: The TemplateData node containing a literal text segment.

        Returns:
            None
        """
        if getattr(node, "data", None):
            self.literals.append(node.data)

    def visit_Const(self, node):  # pylint: disable=invalid-name
        """Handle Const nodes that contain string literal values.

        This handles literal string values within expressions, such as:

            {{ "foo" }}

        Args:
            node: The Const node with a possible string literal ``value``.

        Returns:
            None
        """
        if isinstance(getattr(node, "value", None), str) and node.value:
            self.literals.append(node.value)

    def generic_visit(self, node, *args, **kwargs):
        """Fallback visitor to traverse child nodes.

        Args:
            node: The current AST node being visited.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            None
        """
        for child in node.iter_child_nodes():
            self.visit(child)


def collect_literal_strings(template_str):
    """Parse a Jinja template string and return literal fragments.

    The function uses Django's configured Jinja engine to parse the template and
    extracts both TemplateData and string Const segments without rendering.

    Args:
        template_str: The Jinja template source string to analyze.

    Returns:
        A list of literal string fragments in source order.
    """
    rendering_engine = engines["jinja"]
    ast = rendering_engine.env.parse(template_str)
    collector = LiteralCollector()
    collector.visit(ast)

    return collector.literals


def collect_literal_validation_errors(
    template_fields,
    *,
    check_whitespace_in_value_template=True,
    patterns=DEFAULT_LITERAL_PATTERNS,
):
    """Return mapping of field_name -> list of literal validation errors.

    This validation is performed on literal-only fragments (no evaluation). It can
    optionally flag any presence of whitespace in literal fragments and will flag
    any substring patterns specified via ``patterns``.

    Args:
        template_fields: Iterable of (field_name, template_content) pairs to validate.
        check_whitespace_in_value_template: When True, flag any whitespace in literal fragments in the value template.
        patterns: Tuple of (substring, message) to flag when substring appears in
            any literal fragment for a given field.

    Returns:
        Dict mapping field_name to a de-duplicated list of error messages. Fields
        without violations are omitted from the result.
    """
    results = {}

    for field_name, template_content in template_fields:
        if not template_content:
            continue

        literal_fragments = collect_literal_strings(template_content)
        if not literal_fragments:
            continue

        field_errors = []

        # Check whitespace: only for value_template if enabled; always for other fields
        should_check_whitespace = (field_name != "value_template") or check_whitespace_in_value_template

        if should_check_whitespace and any(_string_contains_space(frag) for frag in literal_fragments):
            field_errors.append("Whitespace in literals is not allowed; use '-' or '.'")

        for bad, message in patterns:
            if any(bad in frag for frag in literal_fragments):
                field_errors.append(message)

        if field_errors:
            seen = set()
            unique_errors = []
            for msg in field_errors:
                if msg not in seen:
                    seen.add(msg)
                    unique_errors.append(msg)
            results[field_name] = unique_errors

    return results


def _string_contains_space(value):
    """Check if a string contains any space characters using regex."""
    return WHITESPACE_REGEX.search(value) is not None
