"""Deduplicação tolerante: a mesma vaga anunciada com títulos ou razões sociais diferentes.

A chave exata (`Job.dedup_key`) resolve o caso fácil, em que as três fontes escrevem
título e empresa igual. Ela falha quando:

- a empresa republica sob outra marca e prefixa o título
  ("ATENTO ESCALADA - Engenheiro(a) de Agentes de IA" / Escalada
   vs "Engenheiro(a) de Agentes de IA" / Atento TI);
- cada portal usa uma razão social diferente ("Grupo Malwee" vs "Malwee Malhas");
- uma das fontes não informa a empresa (acontece no Indeed).

Este módulo compara conjuntos de tokens e roda depois da triagem, sobre algumas
centenas de vagas, e não sobre as milhares de linhas brutas.

Regra deliberadamente conservadora: só funde quando o conjunto de tokens do título
menor está INTEIRAMENTE contido no maior. Sem isso, "Analista de Dados Júnior (SQL)"
e "Analista de Banco de Dados Júnior (DBA)", duas vagas distintas da mesma empresa,
seriam fundidas.
"""
from __future__ import annotations

import logging

from .models import Job
from .text import SENIORITY_TOKENS, company_tokens, title_tokens

log = logging.getLogger("vagas.dedupe")

SOURCE_PREF = {"gupy": 0, "indeed": 1, "linkedin": 2}  # desempate quando a descrição empata
MIN_TOKENS_CONTIDO = 3  # título menor precisa deste tamanho para valer contenção parcial
MIN_TOKEN_LEN_MARCA = 4  # "atento" conta como marca; "ia" ou "sr" não


def same_job(a: Job, b: Job) -> bool:
    """True se `a` e `b` são o mesmo anúncio publicado de formas diferentes."""
    # Identidade do ATS decide sozinha, nos dois sentidos: ids iguais são a mesma
    # vaga ainda que os títulos divirjam, e ids diferentes são vagas diferentes
    # ainda que os títulos coincidam.
    if a.external_id and b.external_id:
        return a.external_id == b.external_id

    ta, tb = title_tokens(a.title), title_tokens(b.title)
    if not ta or not tb:
        return False

    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not small <= large:
        return False
    if small != large and len(small) < MIN_TOKENS_CONTIDO:
        return False
    # níveis diferentes são vagas diferentes, mesmo com o resto do título igual
    if (ta ^ tb) & SENIORITY_TOKENS:
        return False

    ca, cb = company_tokens(a.company), company_tokens(b.company)
    if ca and cb:
        if ca == cb or ca <= cb or cb <= ca:
            return True
        # a marca de uma aparece no prefixo do título da outra (caso Atento/Escalada)
        marcas = {t for t in (large - small) if len(t) >= MIN_TOKEN_LEN_MARCA}
        return bool((ca | cb) & marcas)

    # uma das fontes omitiu a empresa: exige título específico o bastante
    return len(small) >= MIN_TOKENS_CONTIDO


def _melhor(a: Job, b: Job) -> tuple[Job, Job]:
    """Devolve (mantida, descartada) pelo mesmo critério da deduplicação exata."""
    if len(a.description) != len(b.description):
        return (a, b) if len(a.description) > len(b.description) else (b, a)
    if SOURCE_PREF.get(a.source, 9) != SOURCE_PREF.get(b.source, 9):
        return (a, b) if SOURCE_PREF.get(a.source, 9) < SOURCE_PREF.get(b.source, 9) else (b, a)
    return (a, b) if a.id <= b.id else (b, a)  # estável entre rodadas


def merge_duplicates(jobs: list[Job]) -> list[Job]:
    """Funde anúncios equivalentes, preservando a chave dos descartados em `aliases`.

    Guardar os aliases evita que a vaga volte a ser anunciada como nova quando, numa
    rodada seguinte, a cópia sobrevivente for a da outra fonte.
    """
    kept: list[Job] = []
    fundidas = 0
    for job in jobs:
        for i, other in enumerate(kept):
            if not same_job(job, other):
                continue
            manter, descartar = _melhor(other, job)
            manter.aliases = sorted({*manter.aliases, *descartar.aliases, descartar.dedup_key})
            manter.is_new = manter.is_new and descartar.is_new
            # a cópia descartada pode ser a única que trazia o link do ATS
            manter.external_id = manter.external_id or descartar.external_id
            kept[i] = manter
            fundidas += 1
            break
        else:
            kept.append(job)
    if fundidas:
        log.info("dedup tolerante: %d anúncio(s) duplicado(s) fundido(s)", fundidas)
    return kept
