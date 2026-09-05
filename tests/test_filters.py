from datetime import date

import pytest

from vagas_monitor import filters, scoring
from vagas_monitor.config import load_config
from vagas_monitor.models import Job
from vagas_monitor.text import contains_term, normalize


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def job(**kw) -> Job:
    base = dict(source="test", title="", company="Empresa", url="https://x/1")
    base.update(kw)
    return Job(**base)


# --- texto -------------------------------------------------------------------
def test_normalize_remove_acentos():
    assert normalize("Sênior / Júnior — Balneário Camboriú") == "senior / junior — balneario camboriu"


def test_contains_term_respeita_fronteiras():
    assert contains_term(normalize("Analista de BI Jr"), "bi")
    assert not contains_term(normalize("Ambiente"), "bi")
    assert contains_term(normalize("Analista de Dados - Joinville/SC"), "joinville")
    assert not contains_term(normalize("Bahia"), "ai")


# --- cidade / remoto ---------------------------------------------------------
def test_match_city_por_local_e_titulo(cfg):
    assert filters.match_city(job(title="Dev", location="Blumenau, SC, BR"), cfg["cidades"], cfg["cidades_alias"]) == "Blumenau"
    assert filters.match_city(job(title="Analista de Dados - Itajaí/SC", location=""), cfg["cidades"], cfg["cidades_alias"]) == "Itajaí"
    assert filters.match_city(job(title="Dev", location="Camboriú, SC"), cfg["cidades"], cfg["cidades_alias"]) == "Balneário Camboriú"
    assert filters.match_city(job(title="Dev", location="Florianópolis, SC"), cfg["cidades"], cfg["cidades_alias"]) is None


def test_detect_remote_por_titulo_e_flag():
    assert filters.detect_workplace(job(title="Cientista de Dados (Brasil, Remoto)", location="Eldorado do Sul")) == "remote"
    assert filters.detect_workplace(job(title="Dev", remote=True)) == "remote"
    assert filters.detect_workplace(job(title="Analista de QA - Joinville/SC - Híbrido")) == "hybrid"


# --- categoria ---------------------------------------------------------------
def test_classify_titulo_vale_30(cfg):
    p, ordered, pts = filters.classify(job(title="Engenheiro de Dados Pleno"), cfg["categorias"])
    assert p == "dados" and pts["dados"] == 30


def test_classify_descricao_precisa_de_tres_termos(cfg):
    j = job(title="Analista de Sistemas", description="Trabalhará com SQL e Power BI em dashboards.")
    p, _, pts = filters.classify(j, cfg["categorias"])
    assert p == "dados" and pts["dados"] == 12
    j2 = job(title="Analista de Sistemas", description="Conhecimento em SQL e Power BI.")
    assert filters.classify(j2, cfg["categorias"])[0] is None


def test_agente_de_negocios_nao_e_agente_de_ia(cfg):
    assert filters.classify(job(title="Agente de Negócios II - Joinville"), cfg["categorias"])[0] is None
    assert filters.classify(job(title="Engenheiro de Agentes de IA"), cfg["categorias"])[0] == "agentes_ia"


def test_classify_prioridade_desempata(cfg):
    j = job(title="AI Engineer - Agentes de IA e LLMs")
    p, ordered, _ = filters.classify(j, cfg["categorias"])
    assert p == "agentes_ia"
    assert "ia_llm" in ordered


def test_classify_sem_categoria(cfg):
    assert filters.classify(job(title="Assistente de Comércio Exterior"), cfg["categorias"])[0] is None


# --- senioridade ---------------------------------------------------------------
@pytest.mark.parametrize("title,expected", [
    ("Analista de Dados Júnior", "junior"),
    ("Estágio em Dados", "junior"),
    ("Analista de BI Jr.", "junior"),
    ("Engenheiro de Dados Sênior", "senior"),
    ("Tech Lead Dados", "senior"),
    ("Analista de Dados PL", "pleno"),
    ("Analista de Dados", "unknown"),
])
def test_detect_seniority(cfg, title, expected):
    assert filters.detect_seniority(job(title=title), cfg["senioridade"]) == expected


def test_seniority_via_tag_linkedin(cfg):
    assert filters.detect_seniority(job(title="Analista de Dados", tags=["junior"]), cfg["senioridade"]) == "junior"


# --- pontuação -----------------------------------------------------------------
def test_score_junior_na_regiao_supera_senior_remoto(cfg):
    today = date(2026, 9, 5)
    a = job(title="Analista de Dados Júnior", description="Python, SQL e Power BI", date_posted="2026-09-04")
    a.matched_city, a.workplace, a.category, a.categories, a.seniority = "Itajaí", "hybrid", "dados", ["dados"], "junior"
    b = job(title="Engenheiro de Dados Sênior", description="Spark", date_posted="2026-09-04")
    b.matched_city, b.workplace, b.category, b.categories, b.seniority = None, "remote", "dados", ["dados"], "senior"
    sa, ra = scoring.score_job(a, cfg, {"dados": 30}, today)
    sb, rb = scoring.score_job(b, cfg, {"dados": 30}, today)
    assert sa > sb
    assert 0 <= sb <= 100 and sa <= 100
    assert any("Itajaí" in r for r in ra) and any("sênior" in r for r in rb)
