"""Pontuação 0-100 de compatibilidade da vaga com o perfil (regras explícitas, auditáveis)."""
from __future__ import annotations

from datetime import date

from .models import Job
from .text import any_term, normalize


def score_job(job: Job, cfg: dict, cat_points: dict, today: date) -> tuple[int, list[str]]:
    s = 0
    reasons: list[str] = []
    cats = cfg["categorias"]

    pts = cat_points.get(job.category, 0)
    if job.category:
        s += pts
        reasons.append(f"{cats[job.category]['nome']} (+{pts})")
        prio = cats[job.category].get("prioridade", 4)
        s += max(0, 5 - prio)
    extras = [c for c in job.categories if c != job.category]
    if extras:
        s += 3 * len(extras)
        reasons.append("também: " + ", ".join(cats[c]["nome"] for c in extras) + f" (+{3 * len(extras)})")

    if job.seniority == "junior":
        s += 25
        reasons.append("júnior/estágio (+25)")
    elif job.seniority == "pleno":
        s += 8
        reasons.append("pleno (+8)")
    elif job.seniority == "senior":
        s -= 30
        reasons.append("sênior/liderança (-30)")
    else:
        s += 5

    if job.matched_city:
        s += 20
        reasons.append(f"{job.matched_city} (+20)")
    elif job.workplace == "remote":
        s += 12
        reasons.append("remoto (+12)")

    hay = normalize(f"{job.title} | {job.description}")
    skills = any_term(hay, cfg.get("habilidades", []))
    if skills:
        bonus = min(3 * len(skills), 18)
        s += bonus
        reasons.append("skills: " + ", ".join(skills[:6]) + f" (+{bonus})")

    if job.date_posted:
        try:
            age = (today - date.fromisoformat(job.date_posted[:10])).days
            if age <= 7:
                s += 5
                reasons.append("publicada há ≤7 dias (+5)")
        except ValueError:
            pass

    return max(0, min(100, s)), reasons
