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

    @property
    def id(self) -> str:
        # URL completa: no Indeed a chave da vaga vive na query string (?jk=...)
        key = f"{self.source}|{self.url.strip().rstrip('/')}".lower()
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    @property
    def dedup_key(self) -> str:
        """Chave para deduplicar a mesma vaga publicada em fontes diferentes."""
        return f"{normalize(self.title)}|{normalize(self.company)}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        d["description"] = (self.description or "")[:1200]
        return d
