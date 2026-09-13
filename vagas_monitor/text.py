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


# ---------------------------------------------------------------------------
# Tokens usados na deduplicação tolerante (ver vagas_monitor/dedupe.py)
# ---------------------------------------------------------------------------

# Palavras que não distinguem uma vaga de outra: preposições, artigos e rótulos
# de modalidade/contrato que cada fonte escreve à sua maneira.
TITLE_STOP = {
    "a", "o", "as", "os", "um", "uma", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "para", "com", "por", "e", "ou", "the", "and", "for", "of", "in", "at",
    "vaga", "vagas", "efetivo", "efetiva", "clt", "pj", "home", "office", "remoto", "remota", "remote",
    "presencial", "hibrido", "hibrida", "hybrid", "trabalho", "work", "from",
}

# Sufixos societários e termos genéricos de razão social.
COMPANY_STOP = {
    "grupo", "group", "sa", "s/a", "ltda", "me", "epp", "eireli", "sas", "inc", "llc", "ltd", "corp",
    "co", "holding", "holdings", "brasil", "brazil", "br", "do", "da", "de", "e", "the",
    "tecnologia", "tecnologias", "tech", "ti", "it", "solucoes", "solutions", "servicos", "services",
    "consultoria", "consulting", "sistemas", "systems", "vagas", "carreiras", "oportunidades", "talentos",
}

# Marcadores de nível: se dois títulos diferem por um destes, são vagas distintas.
SENIORITY_TOKENS = {
    "junior", "jr", "pleno", "plena", "pl", "senior", "sr", "estagio", "estagiario", "estagiaria",
    "trainee", "aprendiz", "iniciante", "especialista", "specialist", "lead", "principal", "staff",
    "coordenador", "coordenadora", "gerente", "manager", "head", "diretor", "diretora", "assistente",
    "auxiliar", "i", "ii", "iii", "iv", "1", "2", "3",
}

# Códigos de referência que a mesma vaga carrega diferente em cada portal:
# "REF#283517", "ID86295", "- 11686", "12417713 - ANALISTA…".
_REF_CODE = re.compile(r"(?:\b(?:ref|id|cod|codigo|vaga|job)\s*[#:.\-]?\s*\d{3,}\b)|#\d{3,}|\b\d{4,}\b")
_PUNCT = re.compile(r"[^0-9a-z\s]+")


def title_tokens(title: str | None) -> frozenset[str]:
    """Conjunto de tokens significativos do título, para comparar vagas entre fontes.

    Mantém siglas de duas letras: "IA", "BI" e "ML" costumam ser a parte mais
    distintiva do cargo, e descartá-las deixava títulos curtos sem tokens suficientes.
    """
    t = _REF_CODE.sub(" ", normalize(title))
    t = _PUNCT.sub(" ", t)
    return frozenset(w for w in t.split()
                     if (len(w) >= 2 or w in SENIORITY_TOKENS) and w not in TITLE_STOP)


def company_tokens(company: str | None) -> frozenset[str]:
    """Conjunto de tokens do nome da empresa, sem sufixos societários.

    Mantém siglas curtas (EY, GFT), que costumam ser a única parte distintiva.
    Se a razão social for feita só de termos genéricos ("Oportunidades", "Carreiras",
    nomes de página de carreira da Gupy), devolve os tokens crus: um nome genérico
    ainda distingue duas empresas, enquanto um conjunto vazio faria o casamento
    tolerante tratar a empresa como ausente e fundir vagas alheias.
    """
    c = _PUNCT.sub(" ", normalize(company))
    todos = [w for w in c.split() if len(w) >= 2]
    filtrados = [w for w in todos if w not in COMPANY_STOP]
    return frozenset(filtrados or todos)
