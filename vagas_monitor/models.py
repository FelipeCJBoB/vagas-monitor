"""Modelo de dados de uma vaga (uniforme entre fontes)."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional

from .text import normalize


@dataclass
class Job:
    source: str
    title: str
    company: str
    url: str
    location: str = ""
    city: str = ""
    state: str = ""
    remote: bool = False
    workplace: str = "unknown"  # remote | hybrid | onsite | unknown
    date_posted: Optional[str] = None  # ISO YYYY-MM-DD
    description: str = ""
    tags: list = field(default_factory=list)  # dicas extras da fonte (ex.: "estagio")
    # identidade da vaga no ATS de origem ("gupy:12373835"), quando recuperável.
    # Casa a mesma vaga entre fontes sem heurística de texto. Ver vagas_monitor.ats.
    external_id: Optional[str] = None
    # derivados pelo pipeline
    category: Optional[str] = None
    categories: list = field(default_factory=list)
    seniority: str = "unknown"  # junior | pleno | senior | unknown
    matched_city: Optional[str] = None
    score: int = 0
    reasons: list = field(default_factory=list)
    fit: Optional[int] = None  # 0-10, avaliação opcional via Claude
    fit_note: str = ""
    is_new: bool = True
    # chaves de anúncios equivalentes fundidos nesta vaga (ver dedupe.merge_duplicates)
    aliases: list = field(default_factory=list)

    @property
    def id(self) -> str:
        # URL completa: no Indeed a chave da vaga vive na query string (?jk=...)
        key = f"{self.source}|{self.url.strip().rstrip('/')}".lower()
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    @property
    def dedup_key(self) -> str:
        """Chave exata: título e empresa idênticos entre fontes.

        Estrita de propósito. O casamento tolerante (prefixo no título, razão social
        diferente) fica em `vagas_monitor.dedupe`, que registra as chaves fundidas em
        `aliases`. Manter esta chave estrita preserva a precisão de `State.is_new`.
        """
        return f"{normalize(self.title)}|{normalize(self.company)}"

    @property
    def all_keys(self) -> list[str]:
        """Identidade do ATS (se houver), chave própria e as dos anúncios fundidos."""
        ext = [f"ext:{self.external_id}"] if self.external_id else []
        return [*ext, self.dedup_key, *self.aliases]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["description"] = (self.description or "")[:1200]
        return d
