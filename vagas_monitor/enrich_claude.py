"""Avaliação opcional de compatibilidade vaga × perfil com Claude (saída estruturada JSON).

Só roda se ANTHROPIC_API_KEY (ou perfil `ant auth login`) estiver disponível.
Cada vaga custa ~1,5 mil tokens de entrada; com `max_vagas: 25` a rodada sai por centavos.
"""
from __future__ import annotations

import json
import logging
import time

from .models import Job

log = logging.getLogger("vagas.claude")

SCHEMA = {
    "type": "object",
    "properties": {
        "compatibilidade": {"type": "integer", "minimum": 0, "maximum": 10,
                            "description": "0 = nada a ver; 10 = candidatura óbvia para o perfil"},
        "comentario": {"type": "string",
                       "description": "1-2 frases em pt-BR: por que combina (ou não) e o que destacar na candidatura"},
        "alerta": {"type": "string",
                   "description": "Requisito eliminatório que o candidato não atende (ex.: 5 anos de experiência, inglês fluente). Vazio se não houver."},
    },
    "required": ["compatibilidade", "comentario", "alerta"],
    "additionalProperties": False,
}

SYSTEM = """Você é um recrutador técnico experiente em Dados, IA e desenvolvimento de software no Brasil.
Avalie a compatibilidade entre a VAGA e o CANDIDATO abaixo. O candidato busca uma posição júnior
(em transição de carreira, estudante de ADS, com projetos pessoais sólidos em Python/ML/agentes).

Critérios, em ordem: (1) senioridade compatível com júnior/estágio/trainee; (2) aderência técnica
(Python, SQL, Power BI, ML, LLMs/agentes, engenharia de dados); (3) requisitos eliminatórios
(anos de experiência exigidos, inglês fluente, formação concluída); (4) local/remoto.
Seja direto e específico. Responda apenas com o JSON pedido.

=== CANDIDATO ===
"""


def _job_text(job: Job) -> str:
    desc = (job.description or "").strip()
    if len(desc) > 5000:
        desc = desc[:5000] + " […]"
    return (f"=== VAGA ===\nTítulo: {job.title}\nEmpresa: {job.company}\n"
            f"Local: {job.location or '-'} | Modalidade: {job.workplace} | Fonte: {job.source}\n"
            f"Senioridade detectada por regra: {job.seniority}\n\nDescrição:\n{desc or '(sem descrição disponível)'}")


FALHAS_SEGUIDAS_ATE_DESISTIR = 3


def enrich(jobs: list[Job], profile: str, cfg: dict) -> tuple[int, str | None]:
    """Preenche job.fit / job.fit_note nas primeiras `max_vagas` vagas.

    Devolve (quantas avaliou, motivo da falha). O motivo sobe para o relatório: uma
    rodada em que a IA não respondeu precisa dizer isso ao leitor, senão a ausência
    de estrelas fica indistinguível de "nenhuma vaga mereceu nota".

    Desiste depois de algumas falhas seguidas. Erros como saldo insuficiente ou
    chave revogada valem para todas as vagas; insistir só gasta tempo da rodada.
    """
    try:
        import anthropic
    except ImportError:
        log.warning("pacote anthropic não instalado; pulando avaliação por IA")
        return 0, "pacote anthropic não instalado"

    ccfg = cfg.get("claude", {})
    model = ccfg.get("modelo", "claude-opus-5")
    effort = ccfg.get("esforco", "low")
    limit = int(ccfg.get("max_vagas", 25))
    client = anthropic.Anthropic()
    system = [{"type": "text", "text": SYSTEM + profile, "cache_control": {"type": "ephemeral"}}]

    done, seguidas, ultimo_erro = 0, 0, None

    def falhou(motivo: str) -> bool:
        """Registra a falha e diz se é hora de desistir da rodada."""
        nonlocal seguidas, ultimo_erro
        seguidas += 1
        ultimo_erro = motivo[:200]
        if seguidas >= FALHAS_SEGUIDAS_ATE_DESISTIR:
            log.error("avaliação por IA abortada após %d falhas seguidas: %s",
                      seguidas, ultimo_erro)
            return True
        return False

    for job in jobs[:limit]:
        try:
            resp = client.beta.messages.create(
                model=model,
                max_tokens=800,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": _job_text(job)}],
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except anthropic.AuthenticationError:
            log.error("ANTHROPIC_API_KEY inválida; avaliação por IA desativada nesta rodada")
            return done, "chave inválida ou revogada"
        except anthropic.RateLimitError:
            log.warning("rate limit; aguardando 30s")
            time.sleep(30)
            if falhou("limite de requisições da API"):
                break
            continue
        except anthropic.APIStatusError as e:
            log.warning("claude %s: %s", e.status_code, e.message)
            if falhou(f"HTTP {e.status_code}: {e.message}"):
                break
            continue
        except anthropic.APIConnectionError as e:
            log.warning("claude rede: %s", e)
            if falhou(f"falha de rede: {e}"):
                break
            continue

        if resp.stop_reason == "refusal":
            log.warning("claude recusou avaliar '%s'", job.title)
            continue  # recusa é sobre esta vaga, não sobre a rodada
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("resposta não-JSON para '%s'", job.title)
            continue
        try:
            job.fit = max(0, min(10, int(data.get("compatibilidade", 0))))
        except (TypeError, ValueError):
            log.warning("nota fora do formato para '%s'", job.title)
            continue
        note = (data.get("comentario") or "").strip()
        alerta = (data.get("alerta") or "").strip()
        job.fit_note = note + (f" ⚠ {alerta}" if alerta else "")
        done += 1
        seguidas = 0  # a sequência de falhas foi quebrada

    log.info("claude: %d vagas avaliadas (modelo %s)", done, model)
    return done, (ultimo_erro if done == 0 else None)
