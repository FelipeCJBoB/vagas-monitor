"""Avaliação de compatibilidade vaga × perfil, independente de provedor.

O que muda entre Gemini e Claude é só como a chamada é feita e como o erro se
chama. O prompt, o esquema de saída, o disjuntor de falhas e o tratamento da
resposta são os mesmos, e vivem aqui.

A avaliação é sempre opcional: qualquer falha vira um motivo legível que sobe para
o relatório, e a rodada segue sem as notas.
"""
from __future__ import annotations

import json
import logging
import time

from .config import env
from .models import Job
from .providers import DISPONIVEIS, ORDEM_AUTO

log = logging.getLogger("vagas.ia")

FALHAS_SEGUIDAS_ATE_DESISTIR = 3

SYSTEM = """Você é um recrutador técnico experiente em Dados, IA e desenvolvimento de software no Brasil.
Avalie a compatibilidade entre a VAGA e o CANDIDATO abaixo. O candidato busca uma posição júnior
(em transição de carreira, estudante de ADS, com projetos pessoais sólidos em Python/ML/agentes).

Critérios, em ordem: (1) senioridade compatível com júnior/estágio/trainee; (2) aderência técnica
(Python, SQL, Power BI, ML, LLMs/agentes, engenharia de dados); (3) requisitos eliminatórios
(anos de experiência exigidos, inglês fluente, formação concluída); (4) local/remoto.
Seja direto e específico. Responda apenas com o JSON pedido.

=== CANDIDATO ===
"""


def escolher_provedor(cfg: dict) -> str | None:
    """Nome do provedor a usar, ou None se nenhum estiver configurado."""
    escolha = str(cfg.get("provedor", "auto")).lower()
    if escolha in ("nenhum", "none", "off", "false"):
        return None
    if escolha in DISPONIVEIS:
        return escolha if env(DISPONIVEIS[escolha].ENV_VAR) else None
    return next((n for n in ORDEM_AUTO if env(DISPONIVEIS[n].ENV_VAR)), None)


def _job_text(job: Job) -> str:
    desc = (job.description or "").strip()
    if len(desc) > 5000:
        desc = desc[:5000] + " […]"
    return (f"=== VAGA ===\nTítulo: {job.title}\nEmpresa: {job.company or '(não informada)'}\n"
            f"Local: {job.location or '-'} | Modalidade: {job.workplace} | Fonte: {job.source}\n"
            f"Senioridade detectada por regra: {job.seniority}\n\n"
            f"Descrição:\n{desc or '(sem descrição disponível)'}")


def _aplicar(job: Job, bruto: str) -> bool:
    """Escreve a nota na vaga. False se a resposta não veio utilizável."""
    try:
        data = json.loads(bruto)
    except (json.JSONDecodeError, TypeError):
        log.warning("resposta não-JSON para '%s'", job.title)
        return False
    try:
        job.fit = max(0, min(10, int(data.get("compatibilidade", 0))))
    except (TypeError, ValueError):
        log.warning("nota fora do formato para '%s'", job.title)
        return False
    nota = (data.get("comentario") or "").strip()
    alerta = (data.get("alerta") or "").strip()
    job.fit_note = nota + (f" ⚠ {alerta}" if alerta else "")
    return True


def enrich(jobs: list[Job], profile: str, cfg: dict) -> tuple[int, str | None]:
    """Avalia até `max_vagas` vagas. Devolve (quantas avaliou, motivo da falha).

    Desiste depois de algumas falhas seguidas: saldo zerado ou chave inválida valem
    para todas as vagas, e insistir só gasta tempo da rodada.
    """
    nome = escolher_provedor(cfg)
    if not nome:
        return 0, None
    prov = DISPONIVEIS[nome]

    try:
        cliente = prov.criar_cliente(cfg)
    except ImportError:
        log.warning("pacote do provedor %s não instalado", prov.NOME)
        return 0, f"pacote do provedor {prov.NOME} não instalado"
    except Exception as e:  # noqa: BLE001
        return 0, f"não foi possível iniciar {prov.NOME}: {e}"[:200]

    limite = int(cfg.get("max_vagas", 25))
    alvo = jobs[:limite]
    # o nível gratuito limita por minuto; espaçar evita transformar a rodada
    # inteira numa sequência de 429
    intervalo = 60.0 / prov.rpm(cfg) if prov.rpm(cfg) > 0 else 0.0
    system = SYSTEM + profile
    log.info("avaliando %d vaga(s) com %s%s", len(alvo), prov.NOME,
             f" (1 a cada {intervalo:.1f}s)" if intervalo else "")

    done, seguidas, ultimo_erro = 0, 0, None
    for i, job in enumerate(alvo):
        if intervalo and i:
            time.sleep(intervalo)
        try:
            bruto = prov.avaliar(cliente, system, _job_text(job), cfg)
        except Exception as e:  # noqa: BLE001
            motivo, fatal = prov.classificar_erro(e)
            ultimo_erro = f"{prov.NOME}: {motivo}"[:200]
            if fatal:
                log.error("avaliação por IA interrompida: %s", ultimo_erro)
                break
            seguidas += 1
            log.warning("%s (%d falha seguida[s])", ultimo_erro, seguidas)
            if seguidas >= FALHAS_SEGUIDAS_ATE_DESISTIR:
                log.error("avaliação por IA abortada após %d falhas seguidas", seguidas)
                break
            continue

        if _aplicar(job, bruto):
            done += 1
            seguidas = 0

    log.info("%s: %d vaga(s) avaliada(s)", prov.NOME, done)
    return done, (ultimo_erro if done == 0 else None)
