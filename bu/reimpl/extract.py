from pypdf import PdfReader
import re

# -----------------------------
# Cleaning utilities
# -----------------------------
HEADER_FOOTER_PATTERNS_BODY = [
    re.compile(r"^US\s+\d{1,2},\d{3},\d{3}\s+B\d\s*$", re.MULTILINE),
    re.compile(r"^U\.S\.\s+Patent.*Sheet.*US\s+\d{1,2},\d{3},\d{3}\s+B\d\s*$", re.MULTILINE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]

HEADER_FOOTER_PATTERNS_FRONT = [
    # front page: keep the US patent number line; it is metadata we want
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]


def strip_headers_footers(text: str, *, is_front_page: bool = False) -> str:
    pats = HEADER_FOOTER_PATTERNS_FRONT if is_front_page else HEADER_FOOTER_PATTERNS_BODY
    cleaned = text
    for pat in pats:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def dehyphenate(text: str) -> str:
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(reader: PdfReader, page_index: int, *, is_front_page: bool = False) -> str:
    page = reader.pages[page_index]

    t_left = page.extract_text() or ""
    t_right = page.extract_text() or ""
    t = t_left + "\n" + t_right
    t = dehyphenate(t)
    t = strip_headers_footers(t, is_front_page=is_front_page)
    t = normalize_whitespace(t)
    return t
