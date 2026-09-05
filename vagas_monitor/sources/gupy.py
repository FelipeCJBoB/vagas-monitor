"""Gupy — portal público de vagas (API JSON). Muito usado por empresas de SC."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests

from ..models import Job
from ..text import strip_html

log = logging.getLogger("vagas.gupy")

BASE = "https://employability-portal.gupy.io/api/v1/jobs"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) vagas-monitor/1.0"}
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}


def _page(params: dict) -> list[dict]:
    try:
        r = requests.get(BASE, params=params, headers=HEADERS, timeout=40)
        r.raise_for_status()
        return r.json().get("data", []) or []
    except Exception as e:  # noqa: BLE001
        log.warning("gupy %s: %s", params, e)
        return []


def _to_job(j: dict) -> Job:
    tags = []
    t = (j.get("type") or "").lower()
    if "intern" in t or "estag" in t or "trainee" in t:
        tags.append("estagio")
    wp = WORKPLACE.get((j.get("workplaceType") or "").lower(), "unknown")
    city, state = j.get("city") or "", j.get("state") or ""
    remote = bool(j.get("isRemoteWork"))
    return Job(
        source="gupy",
        title=(j.get("name") or "").strip(),
        company=(j.get("careerPageName") or "").strip(),
        url=(j.get("jobUrl") or "").split("?")[0],
        location=", ".join(p for p in (city, state) if p) or ("Remoto" if remote else ""),
        city=city,
        state=state,
        remote=remote,
        workplace="remote" if remote else wp,
        date_posted=(j.get("publishedDate") or "")[:10] or None,
        description=strip_html(j.get("description") or "")[:6000],
        tags=tags,
    )


def collect(terms: list[str], lookback_days: int, include_remote: bool = True,
            state_name: str = "Santa Catarina", max_pages: int = 10) -> list[Job]:
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    raw: dict[int, dict] = {}

    # 1) todas as vagas do estado (paginado) — filtramos por categoria localmente
    for i in range(max_pages):
        data = _page({"jobName": "", "state": state_name, "limit": 100, "offset": i * 100})
        for j in data:
            raw[j["id"]] = j
        if len(data) < 100:
            break
        time.sleep(0.6)

    # 2) remotas por termo de busca
    if include_remote:
        for term in terms:
            for i in range(2):
                data = _page({"jobName": term, "isRemoteWork": "true", "limit": 100, "offset": i * 100})
                for j in data:
                    raw[j["id"]] = j
                if len(data) < 100:
                    break
                time.sleep(0.6)

    jobs = [_to_job(j) for j in raw.values() if (j.get("publishedDate") or "")[:10] >= cutoff]
    log.info("gupy: %d vagas brutas (%d dentro da janela)", len(raw), len(jobs))
    return jobs
