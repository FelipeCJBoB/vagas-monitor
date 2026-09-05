"""Indeed Brasil via python-jobspy (API interna do Indeed; inclui descrição)."""
from __future__ import annotations

import logging
import math
import warnings

from ..models import Job

log = logging.getLogger("vagas.indeed")


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v)


def _b(v) -> bool:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return False
    return bool(v)


def _rows_to_jobs(df) -> list[Job]:
    out: list[Job] = []
    for _, r in df.iterrows():
        location = _s(r.get("location"))
        parts = [p.strip() for p in location.split(",")]
        dp = r.get("date_posted")
        date_posted = None if dp is None or (isinstance(dp, float) and math.isnan(dp)) else str(dp)[:10]
        wfh = _s(r.get("work_from_home_type")).lower()
        remote = _b(r.get("is_remote")) or "remot" in wfh
        workplace = "remote" if remote else ("hybrid" if ("hibr" in wfh or "hybr" in wfh) else "unknown")
        tags = []
        jt = _s(r.get("job_type")).lower()
        if "intern" in jt or "estag" in jt:
            tags.append("estagio")
        out.append(Job(
            source="indeed",
            title=_s(r.get("title")),
            company=_s(r.get("company")),
            url=_s(r.get("job_url")),
            location=location,
            city=parts[0] if parts else "",
            state=parts[1] if len(parts) > 1 else "",
            remote=remote,
            workplace=workplace,
            date_posted=date_posted,
            description=_s(r.get("description")),
            tags=tags,
        ))
    return out


def collect(terms: list[str], lookback_days: int, results_wanted: int = 40,
            include_remote: bool = True, location: str = "Santa Catarina") -> list[Job]:
    warnings.filterwarnings("ignore")
    logging.getLogger("JobSpy").setLevel(logging.CRITICAL)
    from jobspy import scrape_jobs  # import tardio: pesado

    jobs: list[Job] = []
    hours = lookback_days * 24
    for term in terms:
        try:
            df = scrape_jobs(site_name=["indeed"], search_term=term, location=location,
                             country_indeed="brazil", results_wanted=results_wanted,
                             hours_old=hours, verbose=0)
            jobs += _rows_to_jobs(df)
        except Exception as e:  # noqa: BLE001
            log.warning("indeed '%s' SC falhou: %s", term, e)
        if include_remote:
            try:
                df = scrape_jobs(site_name=["indeed"], search_term=term, location="Brasil",
                                 country_indeed="brazil", results_wanted=results_wanted,
                                 hours_old=hours, is_remote=True, verbose=0)
                jobs += _rows_to_jobs(df)
            except Exception as e:  # noqa: BLE001
                log.warning("indeed '%s' remoto falhou: %s", term, e)
    log.info("indeed: %d linhas brutas", len(jobs))
    return jobs
