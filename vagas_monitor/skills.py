"""Ranking das tecnologias que as vagas pedem.

A pergunta é literal: em quantas vagas cada tecnologia aparece? Conta-se uma vez
por vaga, sobre a descrição completa, e ranqueia-se pela contagem. Não há filtro
pelo perfil do candidato nem peso de "lacuna": o ranking descreve o mercado, e
quem lê decide o que fazer com ele.

Os recortes (região x remoto, categoria, nível) são filtros sobre o mesmo
conjunto de vagas, não pesos. O painel refaz a contagem no navegador a partir de
`skills` de cada vaga, com os filtros da barra lateral; o Markdown, o Telegram e o
e-mail usam o ranking geral calculado aqui.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Iterable

import yaml

from .models import Job
from .text import contains_term, normalize

log = logging.getLogger("vagas.skills")


def load_taxonomy(root: Path, nome: str = "skills.yaml") -> dict:
    p = Path(root) / nome
    if not p.exists():
        log.warning("%s não encontrado; o ranking de tecnologias será omitido", nome)
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)))


def _casa_maiusculas(texto: str, termo: str) -> bool:
    """Termo "=React": exige a grafia com maiúsculas, com fronteira de palavra.

    Existe para os nomes que também são palavras comuns em inglês: "React" casa,
    "react quickly" não; "SOLID" casa, "solid experience" não.
    """
    pat = r"(?<![A-Za-z0-9])" + re.escape(_sem_acento(termo)) + r"(?![A-Za-z0-9])"
    return re.search(pat, texto) is not None


def extract(text: str, taxonomia: dict) -> list[str]:
    """Chaves das tecnologias citadas no texto, na ordem da taxonomia."""
    if not text:
        return []
    hay, hay_cs = normalize(text), _sem_acento(text)
    out = []
    for chave, meta in (taxonomia.get("habilidades") or {}).items():
        for termo in meta.get("termos", []):
            termo = str(termo)
            achou = (_casa_maiusculas(hay_cs, termo[1:]) if termo.startswith("=")
                     else contains_term(hay, termo))
            if achou:
                out.append(chave)
                break
    return out


def annotate_jobs(jobs: Iterable[Job], taxonomia: dict) -> int:
    """Grava `job.skills` a partir da descrição COMPLETA, logo após a coleta."""
    com_descricao = 0
    for j in jobs:
        if not j.description:
            j.skills = []
            continue
        com_descricao += 1
        j.skills = extract(f"{j.title}\n{j.description}", taxonomia)
    return com_descricao


def _segmento(j: dict) -> str | None:
    if j.get("matched_city"):
        return "regional"
    if j.get("workplace") == "remote":
        return "remoto"
    return None


def catalogo(taxonomia: dict) -> dict:
    """Nome e grupo de cada chave, para o painel refazer a contagem com filtros."""
    return {k: {"nome": v.get("nome", k), "grupo": v.get("grupo", "")}
            for k, v in ((taxonomia or {}).get("habilidades") or {}).items()}


def analyze(jobs: list[dict], taxonomia: dict) -> dict:
    """Conta em quantas vagas cada tecnologia aparece e ranqueia pela contagem.

    Recebe dicionários (o contexto do relatório), não objetos Job, para que o
    comando `render` consiga refazer a análise a partir de um JSON gravado.

    Só vagas com descrição entram no denominador: as demais não têm o que medir,
    e incluí-las faria toda tecnologia parecer mais rara do que é.
    """
    cat = catalogo(taxonomia)
    if not cat:
        return {}
    base = [j for j in jobs if j.get("description")]
    n = len(base)
    n_seg = {"regional": 0, "remoto": 0}
    for j in base:
        seg = _segmento(j)
        if seg:
            n_seg[seg] += 1

    ranking = []
    for chave, meta in cat.items():
        com = [j for j in base if chave in (j.get("skills") or [])]
        if not com:
            continue
        ranking.append({
            "chave": chave, "nome": meta["nome"], "grupo": meta["grupo"],
            "n": len(com), "pct": round(100 * len(com) / n, 1) if n else 0.0,
            "n_regional": sum(1 for j in com if _segmento(j) == "regional"),
            "n_remoto": sum(1 for j in com if _segmento(j) == "remoto"),
        })
    ranking.sort(key=lambda r: (-r["n"], r["nome"].lower()))
    return {
        "ranking": ranking,
        "catalogo": cat,
        "amostra": {"com_descricao": n, "total": len(jobs),
                    "regional": n_seg["regional"], "remoto": n_seg["remoto"]},
    }


def top(mercado: dict, limite: int = 10) -> list[dict]:
    return (mercado.get("ranking") or [])[:limite]
