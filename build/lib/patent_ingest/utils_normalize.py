from __future__ import annotations
import re

def normalize_text(text: str) -> str:
    t = text
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)  # join hyphenated line breaks
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{4,}", "\n\n\n", t)
    return t.strip() + "\n"
