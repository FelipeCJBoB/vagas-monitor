"""LinkedIn — API pública de convidado (sem login). Respeita localização por cidade."""
from __future__ import annotations

import logging
import random
import re
import time

import requests
from bs4 import BeautifulSoup

from ..models import Job

log = logging.getLogger("vagas.linkedin")

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
JUNIOR_LEVELS = {"estágio", "estagio", "júnior", "junior", "assistente", "internship", "entry level"}


def _get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response | None:
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            log.warning("linkedin rede: %s", e)
            time.sleep(3 * (i + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 503):
            wait = 8 * (i + 1) + random.uniform(0, 3)
            log.warning("linkedin %s — aguardando %.0fs", r.status_code, wait)
            time.sleep(wait)
            continue
        log.warning("linkedin status %s em %s", r.status_code, r.url[:120])
        return None
    return None


def _parse_cards(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    for card in soup.select("div.base-card, li"):
        a = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
        title = card.select_one(".base-search-card__title")
        if not a or not title:
            continue
        company = card.select_one(".base-search-card__subtitle")
        loc = card.select_one(".job-search-card__location")
        tm = card.select_one("time")
        url = a.get("href", "").split("?")[0]
        if not url:
            continue
        location = loc.get_text(strip=True) if loc else ""
        parts = [p.strip() for p in location.split(",")]
        jobs.append(Job(
            source="linkedin",
            title=title.get_text(strip=True),
            company=company.get_text(strip=True) if company else "",
            url=url,
            location=location,
            city=parts[0] if parts else "",
            state=parts[1] if len(parts) > 1 else "",
            date_posted=(tm.get("datetime") if tm else None),
        ))
    # a mesma vaga pode aparecer 2x (div + li)
    seen, out = set(), []
    for j in jobs:
        if j.url not in seen:
            seen.add(j.url)
            out.append(j)
    return out


def search(keywords: str, location: str, lookback_days: int, pages: int = 2,
           remote_only: bool = False, delay: float = 2.0) -> list[Job]:
    out: list[Job] = []
    for page in range(pages):
        params = {"keywords": keywords, "location": location,
                  "f_TPR": f"r{lookback_days * 86400}", "start": page * 10}
        if remote_only:
            params["f_WT"] = "2"
        r = _get(SEARCH, params)
        if r is None:
            break
        found = _parse_cards(r.text)
        out.extend(found)
        if len(found) < 10:
            break
        time.sleep(delay + random.uniform(0, 1))
    return out


def fetch_description(job: Job) -> bool:
    """Busca descrição e nível de experiência da vaga. Retorna True se conseguiu."""
    m = re.search(r"-(\d{6,})/?$", job.url) or re.search(r"(\d{6,})", job.url)
    if not m:
        return False
    r = _get(POSTING.format(id=m.group(1)))
    if r is None:
        return False
    soup = BeautifulSoup(r.text, "html.parser")
    desc = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    crit = {}
    for li in soup.select(".description__job-criteria-item"):
        h = li.select_one(".description__job-criteria-subheader")
        v = li.select_one(".description__job-criteria-text")
        if h and v:
            crit[h.get_text(strip=True)] = v.get_text(strip=True)
    level = next((v for k, v in crit.items() if "experi" in k.lower()), "")
    if level:
        job.tags.append(f"nivel:{level}")
        if level.strip().lower() in JUNIOR_LEVELS:
            job.tags.append("junior")
    prefix = f"Nível de experiência (LinkedIn): {level}. " if level else ""
    job.description = prefix + (desc.get_text(" ", strip=True) if desc else "")
    return bool(desc)


def collect(terms: list[str], anchor_cities: list[str], lookback_days: int,
            include_remote: bool = True, pages: int = 2,
            state_name: str = "Santa Catarina") -> list[Job]:
    jobs: list[Job] = []
    for term in terms:
        for city in anchor_cities:
            jobs += search(term, f"{city}, {state_name}, Brasil", lookback_days, pages)
            time.sleep(1.5 + random.uniform(0, 1))
        if include_remote:
            jobs += search(term, "Brasil", lookback_days, pages, remote_only=True)
            time.sleep(1.5 + random.uniform(0, 1))
    log.info("linkedin: %d cards brutos", len(jobs))
    return jobs
