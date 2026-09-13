"""Avaliação por IA: escolha de provedor, disjuntor de falhas e leitura da resposta.

Contexto de duas falhas reais que motivaram os testes:
- em 13/09/2026 a conta da Anthropic estava sem crédito e a API devolveu 400 vinte
  e cinco vezes seguidas, sem que o relatório dissesse nada;
- o nível gratuito do Gemini limita por minuto, então disparar 25 chamadas
  seguidas viraria uma sequência de 429.
"""
import pytest

from vagas_monitor.config import avaliacao_cfg
from vagas_monitor.enrich import FALHAS_SEGUIDAS_ATE_DESISTIR, enrich, escolher_provedor
from vagas_monitor.models import Job
from vagas_monitor.providers import DISPONIVEIS, anthropic_, gemini

OK = '{"compatibilidade": 8, "comentario": "Boa aderência.", "alerta": ""}'


def _jobs(n=25):
    return [Job(source="gupy", title=f"Analista de Dados {i}", company="ACME",
                url=f"https://g/{i}", description="Python e SQL") for i in range(n)]


class _Prov:
    """Provedor falso: consome uma lista de respostas; exceção é levantada."""

    NOME = "Falso"
    ENV_VAR = "FAKE_API_KEY"

    def __init__(self, respostas, rpm_valor=0, fatais=()):
        self.respostas, self.chamadas, self.rpm_valor = list(respostas), 0, rpm_valor
        self.fatais = fatais

    def criar_cliente(self, cfg):
        return object()

    def avaliar(self, cliente, system, texto, cfg):
        self.chamadas += 1
        r = self.respostas.pop(0) if self.respostas else RuntimeError("acabou")
        if isinstance(r, Exception):
            raise r
        return r

    def classificar_erro(self, exc):
        return (str(exc), type(exc) in self.fatais)

    def rpm(self, cfg):
        return self.rpm_valor


def _instala(monkeypatch, prov):
    monkeypatch.setitem(DISPONIVEIS, "falso", prov)
    monkeypatch.setattr("vagas_monitor.enrich.ORDEM_AUTO", ("falso",))
    monkeypatch.setenv("FAKE_API_KEY", "x")
    return {"provedor": "auto", "max_vagas": 25}


# --- escolha de provedor ----------------------------------------------------
def test_auto_prefere_gemini_quando_as_duas_chaves_existem(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert escolher_provedor({"provedor": "auto"}) == "gemini"


def test_auto_cai_para_anthropic_se_so_ela_tem_chave(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert escolher_provedor({"provedor": "auto"}) == "anthropic"


def test_sem_chave_nenhuma_nao_avalia(monkeypatch):
    assert escolher_provedor({"provedor": "auto"}) is None
    assert enrich(_jobs(3), "perfil", {"provedor": "auto"}) == (0, None)


def test_provedor_explicito_sem_chave_nao_cai_para_o_outro(monkeypatch):
    """Pedir Gemini e receber Claude escondido seria pior que não avaliar."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert escolher_provedor({"provedor": "gemini"}) is None


def test_provedor_desligado(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert escolher_provedor({"provedor": "nenhum"}) is None


# --- disjuntor --------------------------------------------------------------
def test_erro_fatal_para_na_primeira(monkeypatch):
    class SemCredito(Exception):
        pass

    prov = _Prov([SemCredito("conta sem crédito")] * 25, fatais=(SemCredito,))
    done, motivo = enrich(_jobs(), "perfil", _instala(monkeypatch, prov))
    assert done == 0 and prov.chamadas == 1
    assert "sem crédito" in motivo


def test_erro_transitorio_desiste_depois_de_tres(monkeypatch):
    prov = _Prov([RuntimeError("instabilidade")] * 25)
    done, motivo = enrich(_jobs(), "perfil", _instala(monkeypatch, prov))
    assert done == 0 and prov.chamadas == FALHAS_SEGUIDAS_ATE_DESISTIR
    assert "instabilidade" in motivo


def test_falha_isolada_no_meio_nao_aborta(monkeypatch):
    prov = _Prov([OK, RuntimeError("hic"), OK, RuntimeError("hic"), OK])
    done, motivo = enrich(_jobs(5), "perfil", _instala(monkeypatch, prov))
    assert done == 3 and prov.chamadas == 5
    assert motivo is None  # houve nota: a rodada não precisa de aviso


def test_sucesso_preenche_nota_e_comentario(monkeypatch):
    prov = _Prov([OK] * 3)
    jobs = _jobs(3)
    done, motivo = enrich(jobs, "perfil", _instala(monkeypatch, prov))
    assert done == 3 and motivo is None
    assert [j.fit for j in jobs] == [8, 8, 8]
    assert jobs[0].fit_note == "Boa aderência."


def test_alerta_entra_na_nota(monkeypatch):
    prov = _Prov(['{"compatibilidade": 4, "comentario": "Pede 5 anos.", "alerta": "5 anos de experiência"}'])
    jobs = _jobs(1)
    enrich(jobs, "perfil", _instala(monkeypatch, prov))
    assert jobs[0].fit == 4 and "⚠ 5 anos de experiência" in jobs[0].fit_note


@pytest.mark.parametrize("texto", ['{"compatibilidade": "oito"}', "isso não é json",
                                   '{"compatibilidade": null}', ""])
def test_resposta_malformada_nao_quebra(monkeypatch, texto):
    prov = _Prov([texto])
    jobs = _jobs(1)
    done, _ = enrich(jobs, "perfil", _instala(monkeypatch, prov))
    assert done == 0 and jobs[0].fit is None


def test_nota_fora_da_faixa_e_limitada(monkeypatch):
    prov = _Prov(['{"compatibilidade": 47, "comentario": "x", "alerta": ""}'])
    jobs = _jobs(1)
    enrich(jobs, "perfil", _instala(monkeypatch, prov))
    assert jobs[0].fit == 10


def test_respeita_o_teto_de_vagas(monkeypatch):
    prov = _Prov([OK] * 50)
    cfg = _instala(monkeypatch, prov)
    cfg["max_vagas"] = 4
    done, _ = enrich(_jobs(30), "perfil", cfg)
    assert done == 4 and prov.chamadas == 4


# --- limite por minuto ------------------------------------------------------
def test_rpm_espaca_as_chamadas(monkeypatch):
    """Sem espaçamento, o nível gratuito do Gemini devolveria 429 a partir da 11ª."""
    dormidas = []
    monkeypatch.setattr("vagas_monitor.enrich.time.sleep", lambda s: dormidas.append(s))
    prov = _Prov([OK] * 4, rpm_valor=10)
    enrich(_jobs(4), "perfil", _instala(monkeypatch, prov))
    assert dormidas == [6.0, 6.0, 6.0]  # 60/10, e nenhuma antes da primeira


def test_rpm_zero_nao_espaca(monkeypatch):
    dormidas = []
    monkeypatch.setattr("vagas_monitor.enrich.time.sleep", lambda s: dormidas.append(s))
    prov = _Prov([OK] * 4, rpm_valor=0)
    enrich(_jobs(4), "perfil", _instala(monkeypatch, prov))
    assert dormidas == []


# --- contrato dos provedores reais ------------------------------------------
@pytest.mark.parametrize("mod", [gemini, anthropic_])
def test_provedores_reais_expoem_a_interface(mod):
    for attr in ("NOME", "ENV_VAR", "MODELO_PADRAO", "criar_cliente", "avaliar",
                 "classificar_erro", "rpm"):
        assert hasattr(mod, attr), f"{mod.__name__} sem {attr}"


def test_gemini_espaca_por_padrao_e_anthropic_nao():
    assert gemini.rpm({}) > 0      # nível gratuito limita por minuto
    assert anthropic_.rpm({}) == 0  # conta paga não precisa


def test_schema_do_gemini_nao_usa_additional_properties():
    """A API do Gemini rejeita esse campo no response_schema."""
    assert "additionalProperties" not in gemini.SCHEMA
    assert "additionalProperties" in anthropic_.SCHEMA  # a da Anthropic exige


# --- compatibilidade com o config antigo ------------------------------------
def test_config_antigo_continua_valendo():
    velho = {"claude": {"ativo": "auto", "modelo": "claude-opus-5", "esforco": "low", "max_vagas": 9}}
    novo = avaliacao_cfg(velho)
    assert novo["provedor"] == "anthropic" and novo["max_vagas"] == 9
    assert novo["anthropic"]["modelo"] == "claude-opus-5"


def test_config_antigo_desligado_continua_desligado():
    assert avaliacao_cfg({"claude": {"ativo": False}})["provedor"] == "nenhum"


def test_config_novo_tem_precedencia():
    cfg = {"avaliacao": {"provedor": "gemini"}, "claude": {"ativo": "auto"}}
    assert avaliacao_cfg(cfg)["provedor"] == "gemini"
