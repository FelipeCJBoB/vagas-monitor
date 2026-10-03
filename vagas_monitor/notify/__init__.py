"""Canais de notificação: Telegram e e-mail."""
from __future__ import annotations

FONTES = {"gupy": "Gupy", "indeed": "Indeed", "linkedin": "LinkedIn"}


def fontes_com_problema(ctx: dict) -> dict[str, str]:
    """Fontes de vagas que falharam ou vieram vazias nesta rodada.

    O Telegram e o e-mail são o que o Felipe lê: o aviso só no relatório deixou a Gupy
    em zero vagas sem ninguém notar. Falha da IA fica de fora (é só enfeite) e a de
    notificação também (é o próprio canal).
    """
    return {FONTES[k]: v for k, v in (ctx.get("errors") or {}).items() if k in FONTES}

