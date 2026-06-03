"""Parse a grocery shopping list from text (Hebrew or English)."""
from __future__ import annotations
import re
from .models import ShoppingItem

# Patterns that detect a quantity at the start or end of a line
_QTY_PREFIX = re.compile(r"^\s*(\d+)\s+(.+)$")           # "3 חלב 3%"
_QTY_X_SUFFIX = re.compile(r"^(.+?)\s*[xX×]\s*(\d+)\s*$")  # "חלב 3% x3"
_QTY_DASH = re.compile(r"^(.+?)\s*-\s*(\d+)\s*(?:יח'|יח|units?)?\s*$")  # "חלב - 2"


def parse_shopping_list(text: str) -> list[ShoppingItem]:
    """
    Parse a plain-text shopping list.

    Supported formats:
        2 חלב 3%
        יוגורט פרוטאין x4
        ביצים גדולות - 12
        # comment lines and blank lines are ignored
    """
    items: list[ShoppingItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        item = _parse_line(line)
        if item:
            items.append(item)
    return items


def _parse_line(line: str) -> ShoppingItem | None:
    # Try "3 חלב 3%"
    m = _QTY_PREFIX.match(line)
    if m:
        qty = int(m.group(1))
        name = m.group(2).strip()
        return ShoppingItem(name=name, requested_quantity=qty, original_text=line)

    # Try "חלב 3% x3"
    m = _QTY_X_SUFFIX.match(line)
    if m:
        name = m.group(1).strip()
        qty = int(m.group(2))
        return ShoppingItem(name=name, requested_quantity=qty, original_text=line)

    # Try "חלב - 2"
    m = _QTY_DASH.match(line)
    if m:
        name = m.group(1).strip()
        qty = int(m.group(2))
        return ShoppingItem(name=name, requested_quantity=qty, original_text=line)

    # Default: quantity=1
    return ShoppingItem(name=line, requested_quantity=1, original_text=line)


def parse_shopping_list_file(path: str) -> list[ShoppingItem]:
    import pathlib
    text = pathlib.Path(path).read_text(encoding="utf-8")
    return parse_shopping_list(text)
