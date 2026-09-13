"""Identidade da vaga no ATS de origem (Gupy, Solides, Recruitee…).

Portais agregadores republicam a vaga com outro título e às vezes sem o nome da
empresa, mas o link "candidatar-se" aponta para o ATS próprio dela. Desse link
saem duas coisas que nenhuma heurística de texto entrega:

- um identificador exato da vaga, que casa entre fontes sem risco de falso
  positivo (o Indeed e a Gupy expõem o mesmo `jobId`);
- o subdomínio da empresa, que recupera o card quando o Indeed omite o campo.

Exemplo. A mesma vaga aparece como
    Gupy   https://vemserixcsoft.gupy.io/job/eyJqb2JJZCI6MTIzNzM4MzUsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0=
    Indeed https://vemserixcsoft.gupy.io/job/eyJqb2JJZCI6MTIzNzM4MzUsInNvdXJjZSI6ImluZGVlZCJ9
Os tokens diferem porque carregam a origem, mas ambos decodificam para
`{"jobId": 12373835, ...}` — daí sai `gupy:12373835` nos dois casos.
"""
from __future__ import annotations

import base64
import binascii
import json
import re

# <slug>.gupy.io/job/<base64 do {"jobId": N, "source": "..."}>
_GUPY = re.compile(r"https?://([\w-]+)\.gupy\.io/job/([A-Za-z0-9+/=_-]+)", re.I)

# ATS que expõem a empresa no subdomínio, mas sem id decodificável na URL.
_ATS_SUBDOMINIO = re.compile(
    # o slug vem primeiro, às vezes seguido de um rótulo do próprio ATS
    # ("stlflix.vagas.solides.com.br")
    r"https?://([\w-]+)\.(?:[\w-]+\.)?(?:gupy\.io|solides\.com\.br|recruitee\.com|abler\.com\.br"
    r"|kenoby\.com|inhire\.app|quickin\.io|breezy\.hr|factorialhr\.com\.br)",
    re.I,
)

# Subdomínios que não são o nome de uma empresa.
_SLUG_GENERICO = {"www", "app", "jobs", "vagas", "carreiras", "portal", "api", "employability-portal"}


def gupy_job_id(url: str | None) -> int | None:
    """`jobId` embutido no link da Gupy, ou None se a URL não for desse formato."""
    if not url:
        return None
    m = _GUPY.search(url)
    if not m:
        return None
    token = m.group(2)
    token += "=" * (-len(token) % 4)  # o link às vezes vem sem o padding
    try:
        payload = json.loads(base64.urlsafe_b64decode(token))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    job_id = payload.get("jobId") if isinstance(payload, dict) else None
    return job_id if isinstance(job_id, int) else None


def external_id(*urls: str | None) -> str | None:
    """Identidade da vaga no ATS, estável entre fontes. Hoje: apenas Gupy."""
    for url in urls:
        job_id = gupy_job_id(url)
        if job_id is not None:
            return f"gupy:{job_id}"
    return None


def company_slug(*urls: str | None) -> str | None:
    """Subdomínio do ATS, usado só quando a fonte não informou a empresa."""
    for url in urls:
        if not url:
            continue
        m = _ATS_SUBDOMINIO.search(url)
        if m and m.group(1).lower() not in _SLUG_GENERICO:
            return m.group(1)
    return None


def company_from_url(*urls: str | None) -> str:
    """Nome aproximado da empresa a partir do subdomínio: "vem-ser-ixc" -> "Vem Ser Ixc".

    Aproximação assumida: serve para identificar o empregador num card que viria
    em branco. Quando a mesma vaga também chega pela Gupy, a deduplicação por
    `external_id` mantém a cópia com a razão social correta.
    """
    slug = company_slug(*urls)
    if not slug:
        return ""
    return re.sub(r"[-_]+", " ", slug).strip().title()
