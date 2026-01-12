from __future__ import annotations
import re


def normalize_text(text: str) -> str:
    # Common PDF artifacts: hyphenation at line breaks, repeated whitespace, page headers.
    # Keep conservative; you can add more rules after seeing real samples.
    t = text

    # Join hyphenated line breaks: "inter-\nface" -> "interface"
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)

    # Normalize line endings
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    # Collapse excessive spaces (but do not destroy newlines)
    t = re.sub(r"[ \t]+", " ", t)

    # Trim trailing spaces per line
    t = "\n".join(line.rstrip() for line in t.split("\n"))

    # Remove extremely repetitive blank lines
    t = re.sub(r"\n{4,}", "\n\n\n", t)

    return t.strip() + "\n"
