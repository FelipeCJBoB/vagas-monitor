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
        self._keys = {v.get("key") for v in self.data["jobs"].values() if v.get("key")}

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
        return job.id not in self.data["jobs"] and job.dedup_key not in self._keys

    def mark(self, job: Job, today: date) -> None:
        if job.id in self.data["jobs"]:
            self.data["jobs"][job.id]["last_seen"] = today.isoformat()
            return
        self.data["jobs"][job.id] = {
            "key": job.dedup_key, "title": job.title, "company": job.company,
            "url": job.url, "source": job.source, "score": job.score,
            "first_seen": today.isoformat(), "last_seen": today.isoformat(),
        }
        self._keys.add(job.dedup_key)

    def prune(self, keep_days: int = 120, today: date | None = None) -> int:
        today = today or date.today()
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        old = [k for k, v in self.data["jobs"].items()
               if v.get("last_seen", v.get("first_seen", "")) < cutoff]
        for k in old:
            self.data["jobs"].pop(k, None)
        self._keys = {v.get("key") for v in self.data["jobs"].values() if v.get("key")}
        return len(old)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)
