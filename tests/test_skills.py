"""Mapa de habilidades: extração, segmentação e os limites do que a amostra sustenta."""
import pytest
import yaml

from vagas_monitor import skills
from vagas_monitor.config import ROOT
from vagas_monitor.models import Job

TAX = {
    "habilidades": {
        "python": {"nome": "Python", "grupo": "Linguagem", "tenho": "sim", "termos": ["python", "pandas"]},
        "aws":    {"nome": "AWS", "grupo": "Nuvem", "tenho": "nao", "termos": ["aws", "s3"]},
        "sap":    {"nome": "SAP", "grupo": "Corporativo", "tenho": "sim", "termos": ["sap", "abap"]},
        "docker": {"nome": "Docker", "grupo": "Nuvem", "tenho": "parcial", "termos": ["docker", "kubernetes"]},
        "raro":   {"nome": "Raro", "grupo": "X", "tenho": "nao", "termos": ["tecnologia rarissima"]},
    },
    "min_ocorrencias": 2,
}


def _dict_job(seg, skills_list, seniority="junior", desc="tem descrição"):
    return {"matched_city": "Itajaí" if seg == "regional" else None,
            "workplace": "hybrid" if seg == "regional" else "remote",
            "skills": skills_list, "description": desc, "seniority": seniority}


# --- extração ---------------------------------------------------------------
def test_extrai_com_fronteira_de_palavra():
    assert skills.extract("Vaga com Python e AWS", TAX) == ["python", "aws"]
    assert skills.extract("Trabalhamos com SAPataria", TAX) == []  # "sap" dentro de outra palavra
    assert skills.extract("", TAX) == []


def test_extracao_usa_a_descricao_completa():
    """O JSON trunca em 1200 caracteres; os requisitos costumam vir depois disso."""
    longa = "bla " * 400 + "exigimos AWS e Docker"
    assert len(longa) > 1200
    j = Job(source="g", title="Dev", company="X", url="u", description=longa)
    skills.annotate_jobs([j], TAX)
    assert "aws" in j.skills and "docker" in j.skills
    assert "aws" not in j.to_dict()["description"]  # confirma que o truncamento perderia


def test_vaga_sem_descricao_fica_sem_skills():
    j = Job(source="g", title="Dev", company="X", url="u", description="")
    assert skills.annotate_jobs([j], TAX) == 0
    assert j.skills == []


# --- análise ----------------------------------------------------------------
def test_separa_os_dois_mercados():
    jobs = [_dict_job("regional", ["sap", "python"]) for _ in range(12)] + \
           [_dict_job("remoto", ["aws", "python"]) for _ in range(12)]
    m = skills.analyze(jobs, TAX)
    por_nome = {r["nome"]: r for r in m["linhas"]}
    assert por_nome["SAP"]["onde"] == "presencial"
    assert por_nome["AWS"]["onde"] == "remoto"
    assert por_nome["Python"]["onde"] == "ambos"


def test_amostra_pequena_neutraliza_a_comparacao():
    """Com 4 vagas de um lado, uma menção vira 25%: não dá para afirmar tendência."""
    jobs = [_dict_job("regional", ["sap"]) for _ in range(4)] + \
           [_dict_job("remoto", ["aws"]) for _ in range(30)]
    m = skills.analyze(jobs, TAX)
    assert m["amostra"]["comparavel"] is False
    assert all(r["onde"] == "indeterminado" for r in m["linhas"])


def test_habilidade_rara_fica_de_fora():
    jobs = [_dict_job("remoto", ["raro"])] + [_dict_job("remoto", ["aws"]) for _ in range(5)]
    nomes = {r["nome"] for r in skills.analyze(jobs, TAX)["linhas"]}
    assert "Raro" not in nomes and "AWS" in nomes


def test_o_que_ja_domina_tem_prioridade_zero():
    jobs = [_dict_job("remoto", ["python", "aws", "docker"]) for _ in range(12)]
    por_nome = {r["nome"]: r for r in skills.analyze(jobs, TAX)["linhas"]}
    assert por_nome["Python"]["prioridade"] == 0      # domina
    assert por_nome["Docker"]["prioridade"] > 0       # parcial pesa metade
    assert por_nome["AWS"]["prioridade"] > por_nome["Docker"]["prioridade"]


def test_vaga_senior_nao_conta_como_acessivel():
    jobs = [_dict_job("remoto", ["aws"], seniority="senior") for _ in range(10)] + \
           [_dict_job("remoto", ["docker"], seniority="junior") for _ in range(10)]
    por_nome = {r["nome"]: r for r in skills.analyze(jobs, TAX)["linhas"]}
    assert por_nome["AWS"]["pct_acessivel"] == 0      # só aparece em sênior
    assert por_nome["Docker"]["pct_acessivel"] == 100


def test_vaga_sem_descricao_fora_do_denominador():
    """Incluí-las faria toda habilidade parecer mais rara do que é."""
    jobs = [_dict_job("remoto", ["aws"]) for _ in range(5)] + \
           [_dict_job("remoto", [], desc="") for _ in range(50)]
    m = skills.analyze(jobs, TAX)
    assert m["amostra"]["remoto"] == 5 and m["amostra"]["remoto_total"] == 55
    assert {r["nome"]: r for r in m["linhas"]}["AWS"]["pct_remoto"] == 100


def test_prioridades_ignora_o_que_ja_se_tem():
    jobs = [_dict_job("remoto", ["python", "aws"]) for _ in range(12)]
    nomes = [r["nome"] for r in skills.prioridades(skills.analyze(jobs, TAX))]
    assert "Python" not in nomes and "AWS" in nomes


def test_sem_taxonomia_nao_quebra():
    assert skills.analyze([_dict_job("remoto", [])], {}) == {}
    assert skills.extract("Python", {}) == []


# --- taxonomia real ---------------------------------------------------------
def test_skills_yaml_do_repo_e_valido():
    tax = skills.load_taxonomy(ROOT)
    habs = tax["habilidades"]
    assert len(habs) > 30
    for chave, v in habs.items():
        assert v["tenho"] in ("sim", "parcial", "nao"), chave
        assert v.get("termos"), chave
        assert v.get("nome") and v.get("grupo"), chave


@pytest.mark.parametrize("texto,esperado", [
    ("Experiência com SAP ECC e SAP EWM", "sap"),
    ("Conhecimento em Power BI e DAX", "powerbi"),
    ("Stack: LangChain, RAG e embeddings", "agentes"),
    ("Necessário inglês avançado", "ingles"),
])
def test_taxonomia_real_reconhece_termos_do_dia_a_dia(texto, esperado):
    assert esperado in skills.extract(texto, skills.load_taxonomy(ROOT))


# --- agregação por família --------------------------------------------------
def test_familia_soma_tecnologias_concorrentes():
    """AWS e Azure disputam entre si linha a linha; juntas são uma lacuna só."""
    jobs = [_dict_job("remoto", ["aws"]) for _ in range(6)] + \
           [_dict_job("remoto", ["docker"]) for _ in range(6)]
    m = skills.analyze(jobs, TAX)
    nuvem = next(g for g in m["grupos"] if g["grupo"] == "Nuvem")
    assert nuvem["pct_acessivel"] == 100          # toda vaga cita uma das duas
    por_nome = {r["nome"]: r for r in m["linhas"]}
    assert por_nome["AWS"]["pct_acessivel"] == 50  # isolada, parece metade do tamanho


def test_vaga_conta_uma_vez_por_familia():
    jobs = [_dict_job("remoto", ["aws", "docker"]) for _ in range(10)]
    nuvem = next(g for g in skills.analyze(jobs, TAX)["grupos"] if g["grupo"] == "Nuvem")
    assert nuvem["pct_acessivel"] == 100  # e não 200


def test_familia_dominada_e_marcada():
    jobs = [_dict_job("regional", ["sap"]) for _ in range(10)] + \
           [_dict_job("remoto", ["sap"]) for _ in range(10)]
    grupos = {g["grupo"]: g for g in skills.analyze(jobs, TAX)["grupos"]}
    assert grupos["Corporativo"]["dominado"] is True and grupos["Corporativo"]["faltam"] == []


def test_familia_sem_ocorrencia_nao_aparece():
    jobs = [_dict_job("remoto", ["aws"]) for _ in range(10)]
    assert "Corporativo" not in {g["grupo"] for g in skills.analyze(jobs, TAX)["grupos"]}
