"""Estado persistente: vagas já vistas e data da última execução."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Job


class State:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"last_run": None, "jobs": {}}
        self.data.setdefault("jobs", {})
        self._keys = self._collect_keys()

    def _collect_keys(self) -> set[str]:
        """Todas as chaves conhecidas: a própria de cada vaga mais as dos gêmeos fundidos."""
        keys: set[str] = set()
        for v in self.data["jobs"].values():
            if v.get("key"):
                keys.add(v["key"])
            keys.update(v.get("aliases") or ())
        return keys

    # --- agenda -----------------------------------------------------------
    @property
    def first_run(self) -> bool:
        return not self.data.get("last_run")

    def due(self, interval_days: int, now: datetime | None = None) -> bool:
        if self.first_run:
            return True
        now = now or datetime.now()
        last = datetime.fromisoformat(self.data["last_run"])
        # tolerância de 6h para o cron diário não "perder" o dia por minutos
        return now - last >= timedelta(days=interval_days) - timedelta(hours=6)

    def days_since_last_run(self, now: datetime | None = None) -> float | None:
        if self.first_run:
            return None
        now = now or datetime.now()
        return (now - datetime.fromisoformat(self.data["last_run"])).total_seconds() / 86400

    def set_last_run(self, now: datetime | None = None) -> None:
        self.data["last_run"] = (now or datetime.now()).replace(microsecond=0).isoformat()

    # --- vagas ------------------------------------------------------------
    def is_new(self, job: Job) -> bool:
        """Nova = id inédito e nenhuma das suas chaves (própria ou de anúncios fundidos) conhecida."""
        if job.id in self.data["jobs"]:
            return False
        return not any(k in self._keys for k in job.all_keys)

    def mark(self, job: Job, today: date) -> None:
        if job.id in self.data["jobs"]:
            entry = self.data["jobs"][job.id]
            entry["last_seen"] = today.isoformat()
            if job.aliases:  # a rodada pode ter descoberto novos gêmeos
                entry["aliases"] = sorted({*entry.get("aliases", []), *job.aliases})
                self._keys.update(job.aliases)
            return
        self.data["jobs"][job.id] = {
            "key": job.dedup_key, "aliases": list(job.aliases), "title": job.title,
            "company": job.company, "url": job.url, "source": job.source, "score": job.score,
            "first_seen": today.isoformat(), "last_seen": today.isoformat(),
        }
        self._keys.update(job.all_keys)

    def prune(self, keep_days: int = 120, today: date | None = None) -> int:
        today = today or date.today()
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        old = [k for k, v in self.data["jobs"].items()
               if v.get("last_seen", v.get("first_seen", "")) < cutoff]
        for k in old:
            self.data["jobs"].pop(k, None)
        self._keys = self._collect_keys()
        return len(old)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
