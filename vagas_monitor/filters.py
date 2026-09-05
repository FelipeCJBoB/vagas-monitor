"""Classificação de vagas: cidade, remoto, categoria e senioridade."""
from __future__ import annotations

from typing import Optional

from .models import Job
from .text import any_term, contains_term, normalize

REMOTE_TERMS = ["remoto", "remota", "remote", "home office", "home-office", "work from home",
                "teletrabalho", "anywhere", "100% remoto"]
HYBRID_TERMS = ["hibrido", "hibrida", "hybrid"]


def match_city(job: Job, cities: list[str], aliases: dict[str, str] | None = None) -> Optional[str]:
    """Retorna o nome canônico da cidade-alvo encontrada em cidade/local/título, ou None."""
    hay = normalize(" | ".join([job.city or "", job.location or "", job.title or ""]))
    for c in cities:
        if contains_term(hay, c):
            return c
    for alias, canon in (aliases or {}).items():
        if canon in cities and contains_term(hay, alias):
            return canon
    return None


def detect_remote(job: Job) -> bool:
    if job.remote or job.workplace == "remote":
        return True
    hay = normalize(f"{job.title} | {job.location}")
    return bool(any_term(hay, REMOTE_TERMS))


def detect_workplace(job: Job) -> str:
    if detect_remote(job):
        return "remote"
    hay = normalize(f"{job.title} | {job.location} | {' '.join(job.tags)}")
    if job.workplace == "hybrid" or any_term(hay, HYBRID_TERMS):
        return "hybrid"
    if job.workplace in ("onsite", "on-site"):
        return "onsite"
    return job.workplace or "unknown"


def classify(job: Job, categories: dict) -> tuple[Optional[str], list[str], dict]:
    """Pontos por categoria: 30 se bate no título; 12 se >=2 termos batem na descrição."""
    t = normalize(job.title)
    d = normalize(job.description)[:8000]
    hits: dict[str, int] = {}
    for key, cat in categories.items():
        pts = 0
        if any_term(t, cat.get("titulo", [])):
            pts = 30
        else:
            desc_hits = any_term(d, cat.get("descricao", []))
            if len(set(desc_hits)) >= 2:
                pts = 12
        if pts:
            hits[key] = pts
    if not hits:
        return None, [], {}
    primary = min(hits, key=lambda k: (-hits[k], categories[k].get("prioridade", 9)))
    ordered = sorted(hits, key=lambda k: (-hits[k], categories[k].get("prioridade", 9)))
    return primary, ordered, hits


def detect_seniority(job: Job, sen_cfg: dict) -> str:
    t = normalize(job.title)
    tags = normalize(" ".join(job.tags))
    for level in ("junior", "senior", "pleno"):
        if any_term(t, sen_cfg.get(level, [])):
            return level
    if any_term(tags, sen_cfg.get("junior", [])):
        return "junior"
    d = normalize(job.description)[:3000]
    if any_term(d, ["vaga junior", "nivel junior", "perfil junior", "estagio", "estagiario", "trainee"]):
        return "junior"
    return "unknown"


def excluded(job: Job, terms: list[str]) -> bool:
    return bool(any_term(normalize(job.title), terms or []))
