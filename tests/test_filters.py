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
    """Título neutro: quem classifica é a descrição, e ela precisa de 3 termos."""
    j = job(title="Especialista em Operações", description="Trabalhará com SQL e Power BI em dashboards.")
    p, _, pts = filters.classify(j, cfg["categorias"])
    assert p == "dados" and pts["dados"] == 12
    j2 = job(title="Especialista em Operações", description="Conhecimento em SQL e Power BI.")
    assert filters.classify(j2, cfg["categorias"])[0] is None


def test_titulo_vence_descricao_mas_a_segunda_categoria_fica_registrada(cfg):
    """"Analista de Sistemas" é o cargo; dados aparece como categoria secundária."""
    j = job(title="Analista de Sistemas", description="Trabalhará com SQL e Power BI em dashboards.")
    primary, ordered, pts = filters.classify(j, cfg["categorias"])
    assert primary == "sistemas_negocio" and pts["sistemas_negocio"] == 30
    assert "dados" in ordered


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


def test_bonus_de_categoria_mantem_o_alvo_no_topo(cfg):
    """Sem o bônus, uma vaga júnior de ERP na região passava à frente de Dados.

    O acerto de título vale 30 para qualquer categoria, então só a "prioridade"
    (que valia no máximo 3 pontos) não expressava a preferência real.
    """
    from datetime import date
    hoje = date(2026, 9, 13)

    def pontua(titulo, categoria, cidade, senioridade):
        j = job(title=titulo, description="Python e SQL")
        j.matched_city, j.workplace = cidade, "hybrid"
        j.category, j.categories, j.seniority = categoria, [categoria], senioridade
        return scoring.score_job(j, cfg, {categoria: 30}, hoje)[0]

    dados = pontua("Analista de Dados Júnior", "dados", "Itajaí", "junior")
    erp = pontua("Analista de Sistemas Jr", "sistemas_negocio", "Itajaí", "junior")
    assert dados > erp


def test_suporte_tecnico_fica_fora_do_escopo(cfg):
    """Atendimento ao usuário não usa o repertório dele nem leva a Dados."""
    for titulo in ["[Suporte] Assistente de Suporte Técnico", "Analista de Suporte II (HCM)",
                   "Service Desk N1", "Técnico de Help Desk"]:
        assert filters.classify(job(title=titulo), cfg["categorias"])[0] is None, titulo


def test_ponte_de_erp_e_implantacao_continua_dentro(cfg):
    for titulo in ["Implantador de Sistemas", "ANALISTA SAP MM", "Analista de Sistemas Jr",
                   "Analista Funcional de ERP", "Analista de Negócios de Integração"]:
        assert filters.classify(job(title=titulo), cfg["categorias"])[0] == "sistemas_negocio", titulo
