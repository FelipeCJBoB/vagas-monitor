"""Estado persistente: vagas já vistas e data da última execução."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Job


KEY_TTL_DAYS = 30    # ver `is_new`
KEEP_DAYS = 120      # ver `prune`


class State:
    def __init__(self, path: Path, key_ttl_days: int = KEY_TTL_DAYS):
        self.path = Path(path)
        self.key_ttl_days = int(key_ttl_days)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"last_run": None, "jobs": {}}
        self.data.setdefault("jobs", {})
        self._keys = self._collect_keys()

    def _collect_keys(self) -> dict[str, str]:
        """Chave conhecida -> data em que foi vista pela última vez.

        Guardar a data, e não só a chave, é o que permite a `is_new` distinguir
        "já anunciei esta vaga" de "esta empresa abriu de novo a mesma posição".
        """
        keys: dict[str, str] = {}
        for v in self.data["jobs"].values():
            visto = v.get("last_seen") or v.get("first_seen") or ""
            for k in (v.get("key"), *(v.get("aliases") or ()), *(v.get("ext_keys") or ())):
                if k and visto > keys.get(k, ""):
                    keys[k] = visto
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
    def is_new(self, job: Job, today: date | None = None) -> bool:
        """Nova = URL inédita e nenhuma chave equivalente vista nos últimos `key_ttl_days`.

        A janela existe porque a chave é só título e empresa. Sem ela, uma posição
        reaberta meses depois na mesma empresa nunca seria anunciada: bastava o par
        ter aparecido uma vez dentro do período de retenção do estado.

        A identidade do ATS (`ext:gupy:123`) é exata e não deveria expirar, mas usa
        a mesma janela: a vaga que continua aberta é revista a cada rodada e tem a
        data renovada, então só expira quem saiu do ar.
        """
        if job.id in self.data["jobs"]:
            return False
        today = today or date.today()
        cutoff = (today - timedelta(days=self.key_ttl_days)).isoformat()
        return not any(self._keys.get(k, "") >= cutoff for k in job.all_keys)

    def mark(self, job: Job, today: date) -> None:
        hoje = today.isoformat()
        ext = [f"ext:{job.external_id}"] if job.external_id else []
        entry = self.data["jobs"].get(job.id)
        if entry is not None:
            entry["last_seen"] = hoje
            # a rodada pode ter descoberto novos gêmeos ou o link do ATS
            if job.aliases:
                entry["aliases"] = sorted({*entry.get("aliases", []), *job.aliases})
            if ext:
                entry["ext_keys"] = sorted({*entry.get("ext_keys", []), *ext})
        else:
            self.data["jobs"][job.id] = {
                "key": job.dedup_key, "aliases": list(job.aliases), "ext_keys": ext,
                "title": job.title, "company": job.company, "url": job.url,
                "source": job.source, "score": job.score,
                "first_seen": hoje, "last_seen": hoje,
            }
        for k in job.all_keys:
            self._keys[k] = hoje

    def prune(self, keep_days: int = KEEP_DAYS, today: date | None = None) -> int:
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
