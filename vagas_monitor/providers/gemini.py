"""Provedor Gemini, via API do Google AI Studio.

Sobre a chave: a assinatura Gemini Pro (Google One AI Premium) NÃO dá acesso à API.
A chave sai do AI Studio (aistudio.google.com/apikey) e é gratuita para qualquer
conta Google, com ou sem assinatura. O nível gratuito é permanente e limitado por
requisições por minuto, não por créditos que acabam.

Duas consequências práticas para esta automação:

- o limite é por minuto, então as chamadas precisam ser espaçadas. 25 vagas a
  10 RPM levam pouco mais de dois minutos, o que é irrelevante numa rodada que
  já gasta doze minutos coletando;
- no nível gratuito o Google pode usar entrada e saída para treinar modelos. Aqui
  isso significa anúncios de vaga, que são públicos, e o `perfil.md`, que está num
  repositório público. Quem não quiser mesmo assim deve ativar cobrança na conta
  ou usar `provedor: anthropic`.
"""
from __future__ import annotations

import logging

NOME = "Gemini"
ENV_VAR = "GEMINI_API_KEY"
# Alias que o Google troca a cada release, com aviso prévio de duas semanas. Numa
# automação que roda sozinha por meses, isso vale mais que fixar "gemini-3.6-flash"
# e descobrir meses depois que o modelo saiu do ar.
MODELO_PADRAO = "gemini-flash-latest"
RPM_PADRAO = 10  # nível gratuito do Flash

log = logging.getLogger("vagas.gemini")

# O Gemini rejeita `additionalProperties` no response_schema, então o esquema aqui
# é o mesmo conteúdo sem esse campo. Ver providers/anthropic_.py para a versão estrita.
SCHEMA = {
    "type": "object",
    "properties": {
        "compatibilidade": {"type": "integer",
                            "description": "0 = nada a ver; 10 = candidatura óbvia para o perfil"},
        "comentario": {"type": "string",
                       "description": "1-2 frases em pt-BR: por que combina (ou não) e o que destacar"},
        "alerta": {"type": "string",
                   "description": "Requisito eliminatório que o candidato não atende. Vazio se não houver."},
    },
    "required": ["compatibilidade", "comentario", "alerta"],
}


def criar_cliente(cfg: dict):
    from google import genai  # import tardio: o pacote só é necessário se o provedor for usado

    return genai.Client()


def avaliar(cliente, system: str, texto: str, cfg: dict) -> str:
    from google.genai import types

    g = (cfg.get("gemini") or {})
    resp = cliente.models.generate_content(
        model=g.get("modelo", MODELO_PADRAO),
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0,
            max_output_tokens=800,
        ),
    )
    return resp.text or ""


def classificar_erro(exc: Exception) -> tuple[str, bool]:
    """(motivo legível, é fatal para a rodada?)"""
    from google.genai import errors

    if isinstance(exc, errors.ClientError):
        code = getattr(exc, "code", None) or getattr(exc, "status", "")
        msg = str(getattr(exc, "message", exc))
        if code == 429:
            return (f"limite de requisições do nível gratuito atingido: {msg}", False)
        if code in (401, 403):
            return ("chave do Gemini inválida, revogada ou sem permissão", True)
        if code == 404:
            return (f"modelo não encontrado — ajuste `avaliacao.gemini.modelo`: {msg}", True)
        return (f"HTTP {code}: {msg}", False)
    if isinstance(exc, errors.ServerError):
        return (f"instabilidade no serviço: {exc}", False)
    return (f"{type(exc).__name__}: {exc}", False)


def rpm(cfg: dict) -> int:
    return int((cfg.get("gemini") or {}).get("rpm", RPM_PADRAO))
