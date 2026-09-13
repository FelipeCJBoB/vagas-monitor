"""Provedores de avaliação por IA.

Cada módulo expõe a mesma interface mínima, para que `enrich.py` não saiba de qual
serviço veio a nota:

    NOME            rótulo curto usado em log e relatório
    ENV_VAR         variável de ambiente que habilita o provedor
    criar_cliente(cfg)              -> cliente pronto, ou levanta
    avaliar(cliente, system, texto, cfg) -> str com o JSON da resposta
    classificar_erro(exc)          -> (motivo legível, fatal?)

`fatal` distingue o erro que não adianta repetir (chave inválida, saldo zerado)
daquele que pode passar na próxima vaga (instabilidade, limite momentâneo).
"""
from __future__ import annotations

from . import anthropic_, gemini

DISPONIVEIS = {"gemini": gemini, "anthropic": anthropic_}

# Ordem do modo `auto`. Gemini primeiro porque o nível gratuito do AI Studio cobre
# com folga o volume desta automação (25 vagas a cada 5 dias), enquanto a API da
# Anthropic é pré-paga. Troque em `avaliacao.provedor` se preferir o contrário.
ORDEM_AUTO = ("gemini", "anthropic")
