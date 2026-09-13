"""Avaliação por IA: desistir cedo de falhas sistemáticas e sempre reportá-las.

Na rodada de 13/09 a conta estava sem crédito e a API devolveu 400 vinte e cinco
vezes seguidas. A rodada sobreviveu, mas o relatório não disse nada: a ausência de
estrelas ficou indistinguível de "nenhuma vaga mereceu nota".
"""
import anthropic
import httpx2
import pytest

from vagas_monitor.enrich_claude import FALHAS_SEGUIDAS_ATE_DESISTIR, enrich
from vagas_monitor.models import Job

CFG = {"claude": {"modelo": "claude-opus-5", "esforco": "low", "max_vagas": 25}}


def _jobs(n=25):
    return [Job(source="gupy", title=f"Analista de Dados {i}", company="ACME",
                url=f"https://g/{i}", description="Python e SQL") for i in range(n)]


def _erro_status(status: int, mensagem: str) -> anthropic.APIStatusError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(status, request=req, json={"error": {"message": mensagem}})
    classe = anthropic.RateLimitError if status == 429 else anthropic.APIStatusError
    return classe(mensagem, response=resp, body=None)


class _ClienteFalso:
    """Devolve o que a lista `respostas` mandar: exceção é levantada, resto é retornado."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0
        self.beta = self
        self.messages = self

    def create(self, **kwargs):
        self.chamadas += 1
        r = self.respostas.pop(0) if self.respostas else self.respostas
        if isinstance(r, Exception):
            raise r
        return r


class _Bloco:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Resposta:
    stop_reason = "end_turn"

    def __init__(self, texto):
        self.content = [_Bloco(texto)]


def _instala(monkeypatch, respostas) -> _ClienteFalso:
    cliente = _ClienteFalso(respostas)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: cliente)
    return cliente


OK = '{"compatibilidade": 8, "comentario": "Boa aderência.", "alerta": ""}'


def test_saldo_insuficiente_desiste_cedo_e_reporta(monkeypatch):
    """25 chamadas com o mesmo 400 viravam 25 requisições inúteis."""
    erro = _erro_status(400, "Your credit balance is too low")
    cliente = _instala(monkeypatch, [erro] * 25)

    done, motivo = enrich(_jobs(), "perfil", CFG)

    assert done == 0
    assert cliente.chamadas == FALHAS_SEGUIDAS_ATE_DESISTIR
    assert "400" in motivo and "credit balance" in motivo


def test_chave_invalida_para_na_primeira(monkeypatch):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(401, request=req, json={"error": {"message": "invalid x-api-key"}})
    cliente = _instala(monkeypatch, [anthropic.AuthenticationError("invalid", response=resp, body=None)])

    done, motivo = enrich(_jobs(), "perfil", CFG)

    assert done == 0 and cliente.chamadas == 1
    assert "chave inválida" in motivo


def test_falha_isolada_no_meio_nao_aborta(monkeypatch):
    """Uma vaga que falha não pode custar as outras: a sequência é zerada a cada acerto."""
    cliente = _instala(monkeypatch, [
        _Resposta(OK), _erro_status(500, "erro interno"), _Resposta(OK),
        _erro_status(500, "erro interno"), _Resposta(OK),
    ])

    done, motivo = enrich(_jobs(5), "perfil", CFG)

    assert done == 3 and cliente.chamadas == 5
    assert motivo is None  # houve nota: a rodada não precisa de aviso


def test_sucesso_completo(monkeypatch):
    _instala(monkeypatch, [_Resposta(OK)] * 3)
    jobs = _jobs(3)

    done, motivo = enrich(jobs, "perfil", CFG)

    assert done == 3 and motivo is None
    assert [j.fit for j in jobs] == [8, 8, 8]
    assert jobs[0].fit_note == "Boa aderência."


def test_alerta_entra_na_nota(monkeypatch):
    _instala(monkeypatch, [_Resposta('{"compatibilidade": 4, "comentario": "Pede 5 anos.", '
                                     '"alerta": "experiência mínima de 5 anos"}')])
    jobs = _jobs(1)
    enrich(jobs, "perfil", CFG)
    assert jobs[0].fit == 4
    assert "⚠ experiência mínima de 5 anos" in jobs[0].fit_note


@pytest.mark.parametrize("texto", ['{"compatibilidade": "oito"}', "isso não é json", '{"compatibilidade": null}'])
def test_resposta_malformada_nao_quebra(monkeypatch, texto):
    _instala(monkeypatch, [_Resposta(texto)])
    jobs = _jobs(1)
    done, _ = enrich(jobs, "perfil", CFG)
    assert done == 0 and jobs[0].fit is None


def test_nota_fora_da_faixa_e_limitada(monkeypatch):
    _instala(monkeypatch, [_Resposta('{"compatibilidade": 47, "comentario": "x", "alerta": ""}')])
    jobs = _jobs(1)
    enrich(jobs, "perfil", CFG)
    assert jobs[0].fit == 10


def test_respeita_o_teto_de_vagas(monkeypatch):
    cliente = _instala(monkeypatch, [_Resposta(OK)] * 50)
    cfg = {"claude": {"max_vagas": 4}}
    done, _ = enrich(_jobs(30), "perfil", cfg)
    assert done == 4 and cliente.chamadas == 4
