"""Small pure helpers shared by the Markdown report renderers."""

from pathlib import Path

NONE_LINE = "_None._"


def cell(text: object) -> str:
    """Make text safe inside a Markdown table cell or list item."""
    return " ".join(str(text).split()).replace("|", "\\|")


def code(path: Path | str) -> str:
    return f"`{cell(path)}`"
