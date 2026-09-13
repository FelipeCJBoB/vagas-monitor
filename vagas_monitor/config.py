"""Carrega config.yaml, .env e o perfil profissional."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | os.PathLike | None = None) -> dict:
    load_dotenv(ROOT / ".env")
    p = Path(path) if path else ROOT / "config.yaml"
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_root"] = ROOT
    return cfg


def load_profile(cfg: dict) -> str:
    p = ROOT / cfg.get("perfil", "perfil.md")
    return p.read_text(encoding="utf-8") if p.exists() else ""


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def avaliacao_cfg(cfg: dict) -> dict:
    """Seção de avaliação por IA, aceitando o formato antigo.

    Até 09/2026 a configuração era `claude: {ativo, modelo, esforco, max_vagas}`,
    de quando havia um provedor só. Quem tiver um config.yaml antigo continua
    funcionando sem editar nada.
    """
    if cfg.get("avaliacao"):
        return dict(cfg["avaliacao"])
    antigo = cfg.get("claude") or {}
    if not antigo:
        return {}
    ativo = antigo.get("ativo", "auto")
    return {
        "provedor": "nenhum" if ativo is False else "anthropic",
        "max_vagas": antigo.get("max_vagas", 25),
        "anthropic": {k: v for k, v in
                      (("modelo", antigo.get("modelo")), ("esforco", antigo.get("esforco")))
                      if v is not None},
    }
