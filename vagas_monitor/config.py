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
