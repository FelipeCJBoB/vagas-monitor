"""Orquestra a rodada: coleta → filtra → pontua → (IA) → relatórios → estado → notificações."""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import filters, report, scoring
from .config import ROOT, env, load_config, load_profile
from .models import Job
from .sources import gupy, indeed, linkedin
from .state import State

log = logging.getLogger("vagas")
TZ = ZoneInfo("America/Sao_Paulo")
SOURCE_PREF = {"gupy": 0, "indeed": 1, "linkedin": 2}  # desempate na deduplicação entre fontes


def _on(flag, *envs: str) -> bool:
    """`ativo: auto` liga quando todas as variáveis de ambiente existem."""
    if flag is True:
        return True
    if flag is False:
        return False
    return all(env(e) for e in envs)


def collect_all(cfg: dict, lookback: int, errors: dict, skip: tuple[str, ...] = ()) -> tuple[list[Job], dict]:
    terms = cfg["termos_busca"]
    inc_remote = bool(cfg.get("incluir_remoto", True))
    src = cfg.get("fontes", {})
    jobs: list[Job] = []
    counts: dict[str, int] = {}

    def run_source(name, fn):
        if not src.get(name, {}).get("ativo", True) or name in skip:
            return
        log.info("coletando %s …", name)
        try:
            got = fn()
            counts[name] = len(got)
            jobs.extend(got)
        except Exception as e:  # noqa: BLE001
            log.exception("fonte %s falhou", name)
            errors[name] = f"{type(e).__name__}: {e}"[:200]
            counts[name] = 0

    run_source("gupy", lambda: gupy.collect(terms, lookback, inc_remote))
    run_source("indeed", lambda: indeed.collect(terms, lookback, int(src.get("indeed", {}).get("resultados_por_busca", 40)), inc_remote))
    li = src.get("linkedin", {})
    run_source("linkedin", lambda: linkedin.collect(terms, li.get("cidades_ancora", ["Itajaí", "Blumenau", "Joinville"]),
                                                    lookback, inc_remote, int(li.get("paginas", 2))))
    return jobs, counts


def annotate(job: Job, cfg: dict, today: date) -> bool:
    """Preenche cidade/modalidade/categoria/senioridade. Retorna False se a vaga está fora do escopo."""
    job.matched_city = filters.match_city(job, cfg["cidades"], cfg.get("cidades_alias"))
    job.workplace = filters.detect_workplace(job)
    if not job.matched_city and not (job.workplace == "remote" and cfg.get("incluir_remoto", True)):
        return False
    if filters.excluded(job, cfg.get("excluir_titulo", [])):
        return False
    primary, ordered, pts = filters.classify(job, cfg["categorias"])
    if not primary:
        return False
    job.category, job.categories = primary, ordered
    job.seniority = filters.detect_seniority(job, cfg["senioridade"])
    job.score, job.reasons = scoring.score_job(job, cfg, pts, today)
    return True


def dedupe(jobs: list[Job]) -> list[Job]:
    by_id: dict[str, Job] = {}
    for j in jobs:
        if j.id not in by_id:
            by_id[j.id] = j
    by_key: dict[str, Job] = {}
    for j in by_id.values():
        k = j.dedup_key
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = j
            continue
        better = (len(j.description) > len(cur.description)) or \
                 (len(j.description) == len(cur.description) and SOURCE_PREF.get(j.source, 9) < SOURCE_PREF.get(cur.source, 9))
        if better:
            by_key[k] = j
    return list(by_key.values())


def run(force: bool = False, dry_run: bool = False, notify: bool = True, lookback: int | None = None,
        config_path: str | None = None, skip: tuple[str, ...] = ()) -> dict:
    cfg = load_config(config_path)
    profile = load_profile(cfg)
    now = datetime.now(TZ)
    now_naive = now.replace(tzinfo=None)
    today = now.date()
    state = State(ROOT / "state" / "seen.json")
    interval = int(cfg.get("intervalo_dias", 5))

    if not force and not state.due(interval, now_naive):
        d = state.days_since_last_run(now_naive)
        log.info("última execução há %.1f dias (cadência: %d). Nada a fazer — use --force para rodar agora.", d, interval)
        return {"skipped": True, "days_since_last_run": d}

    lb = int(lookback or (cfg.get("first_run_lookback_days", 30) if state.first_run else cfg.get("lookback_days", 7)))
    log.info("rodada %s — janela %d dias — %s", today, lb, "primeira execução" if state.first_run else "execução regular")

    errors: dict[str, str] = {}
    raw, counts = collect_all(cfg, lb, errors, skip)
    log.info("%d vagas brutas de %d fontes", len(raw), len(counts))

    # 1ª passada: escopo + categoria pelo título (LinkedIn ainda sem descrição)
    scoped = [j for j in dedupe(raw) if annotate(j, cfg, today)]
    for j in scoped:
        j.is_new = state.is_new(j)
    log.info("%d vagas no escopo (%d novas)", len(scoped), sum(j.is_new for j in scoped))

    # descrições do LinkedIn só para vagas novas (1 requisição cada, limitado)
    li = cfg.get("fontes", {}).get("linkedin", {})
    if li.get("buscar_descricao", True) and "linkedin" not in skip:
        cand = sorted((j for j in scoped if j.source == "linkedin" and j.is_new and not j.description),
                      key=lambda j: -j.score)[: int(li.get("max_descricoes", 60))]
        ok = 0
        for j in cand:
            ok += int(linkedin.fetch_description(j))
        if cand:
            log.info("linkedin: descrição obtida para %d/%d vagas novas", ok, len(cand))

    # 2ª passada: com descrições completas, reclassifica e pontua tudo
    jobs = [j for j in scoped if annotate(j, cfg, today)]
    jobs.sort(key=lambda j: (not j.is_new, -j.score, j.date_posted or ""))
    new_jobs = [j for j in jobs if j.is_new]

    ai_done = 0
    if _on(cfg.get("claude", {}).get("ativo", "auto"), "ANTHROPIC_API_KEY") and new_jobs:
        from .enrich_claude import enrich
        ai_done = enrich(new_jobs, profile, cfg)

    ctx = report.build_context(jobs, cfg, now, lb, counts, errors,
                               {"known_jobs": len(state.data["jobs"]), "first_run": state.first_run})
    paths = report.write_all(ctx, cfg)
    log.info("relatórios: %s | %s", paths["md"].relative_to(ROOT), paths["html"].relative_to(ROOT))

    if not dry_run:
        for j in jobs:
            state.mark(j, today)
        state.set_last_run(now_naive)
        pruned = state.prune(today=today)
        state.save()
        log.info("estado salvo (%d vagas conhecidas, %d expiradas)", len(state.data["jobs"]), pruned)

    sent: dict[str, bool] = {}
    if notify and not dry_run:
        ncfg = cfg.get("notificacoes", {})
        if _on(ncfg.get("telegram", {}).get("ativo", "auto"), "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            from .notify import telegram
            n = telegram.send(env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"), ctx, int(ncfg.get("telegram", {}).get("top_n", 15)))
            sent["telegram"] = n > 0
            log.info("telegram: %d mensagem(ns) enviada(s)", n)
        if _on(ncfg.get("email", {}).get("ativo", "auto"), "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
            from .notify import email_
            ok = email_.send(env("SMTP_HOST", "smtp.gmail.com"), int(env("SMTP_PORT", "465")), env("SMTP_USER"),
                             env("SMTP_PASSWORD"), env("EMAIL_TO"), ctx, paths["md"])
            sent["email"] = ok
            log.info("email: %s", "enviado" if ok else "falhou")

    return {
        "skipped": False, "date": today.isoformat(), "lookback_days": lb, "raw": len(raw),
        "in_scope": len(jobs), "new": len(new_jobs), "ai_evaluated": ai_done,
        "sources": counts, "errors": errors, "sent": sent,
        "paths": {k: str(v) for k, v in paths.items()},
    }
