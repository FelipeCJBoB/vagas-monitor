"""Utilitários de texto: normalização sem acentos e busca por termo com fronteira de palavra."""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup


def normalize(s: str | None) -> str:
    """Minúsculas, sem acentos, espaços colapsados. 'Sênior/PL' -> 'senior/pl'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def contains_term(text_norm: str, term: str) -> bool:
    """True se `term` aparece em `text_norm` como palavra/expressão inteira (não dentro de outra palavra)."""
    t = normalize(term)
    if not t or not text_norm:
        return False
    pat = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
    return re.search(pat, text_norm) is not None


def any_term(text_norm: str, terms: list[str]) -> list[str]:
    """Retorna os termos (originais) encontrados no texto normalizado."""
    return [t for t in terms if contains_term(text_norm, t)]


def strip_html(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
