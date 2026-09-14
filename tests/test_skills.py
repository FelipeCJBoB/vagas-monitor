"""Ranking de tecnologias: extração literal e contagem por vaga."""
import pytest

from vagas_monitor import skills
from vagas_monitor.config import ROOT
from vagas_monitor.models import Job

TAX = {
    "habilidades": {
        "python": {"nome": "Python", "grupo": "Linguagem", "termos": ["python"]},
        "pandas": {"nome": "Pandas", "grupo": "Dados", "termos": ["pandas"]},
        "aws":    {"nome": "AWS", "grupo": "Nuvem", "termos": ["aws"]},
        "sap":    {"nome": "SAP", "grupo": "Corporativo", "termos": ["sap"]},
        "react":  {"nome": "React", "grupo": "Front-end", "termos": ["=React", "reactjs"]},
    },
}


def _dict_job(seg, skills_list, desc="tem descrição"):
    return {"matched_city": "Itajaí" if seg == "regional" else None,
            "workplace": "hybrid" if seg == "regional" else "remote",
            "skills": skills_list, "description": desc, "seniority": "senior"}


# --- extração ---------------------------------------------------------------
def test_extrai_com_fronteira_de_palavra():
    assert skills.extract("Vaga com Python e AWS", TAX) == ["python", "aws"]
    assert skills.extract("Trabalhamos com SAPataria", TAX) == []  # "sap" dentro de outra palavra
    assert skills.extract("", TAX) == []


def test_contagem_e_literal_sem_inferir_tecnologia_vizinha():
    """Pandas não conta como Python: cada tecnologia só pelo próprio nome."""
    assert skills.extract("Experiência com pandas", TAX) == ["pandas"]


def test_termo_com_igual_respeita_maiusculas():
    """"react quickly" num anúncio em inglês não é o framework."""
    assert "react" in skills.extract("Front-end em React e Next", TAX)
    assert "react" not in skills.extract("You must react quickly to incidents", TAX)
    assert "react" in skills.extract("stack: reactjs", TAX)


def test_extracao_usa_a_descricao_completa():
    """Os requisitos costumam vir no fim do anúncio, depois de qualquer resumo."""
    longa = "bla " * 400 + "exigimos AWS"
    j = Job(source="g", title="Dev", company="X", url="u", description=longa)
    skills.annotate_jobs([j], TAX)
    assert j.skills == ["aws"]
    assert "AWS" in j.to_dict()["description"]  # o JSON guarda a descrição inteira


def test_vaga_sem_descricao_fica_sem_skills():
    j = Job(source="g", title="Dev", company="X", url="u", description="")
    assert skills.annotate_jobs([j], TAX) == 0
    assert j.skills == []


# --- ranking ----------------------------------------------------------------
def test_ranking_ordena_pela_contagem_de_vagas():
    jobs = [_dict_job("remoto", ["aws", "python"]) for _ in range(5)] + \
           [_dict_job("regional", ["sap", "python"]) for _ in range(3)]
    rk = skills.analyze(jobs, TAX)["ranking"]
    assert [(r["nome"], r["n"]) for r in rk] == [("Python", 8), ("AWS", 5), ("SAP", 3)]
    assert rk[0]["pct"] == 100 and rk[0]["n_regional"] == 3 and rk[0]["n_remoto"] == 5


def test_ranking_nao_filtra_por_perfil_nem_senioridade():
    """Vaga sênior conta igual: o ranking descreve o mercado, não o candidato."""
    jobs = [_dict_job("remoto", ["aws"]) for _ in range(4)]
    assert skills.analyze(jobs, TAX)["ranking"][0]["n"] == 4


def test_tecnologia_citada_uma_vez_aparece():
    rk = skills.analyze([_dict_job("remoto", ["sap"])], TAX)["ranking"]
    assert rk and rk[0]["nome"] == "SAP" and rk[0]["n"] == 1


def test_vaga_sem_descricao_fora_do_denominador():
    """Incluí-las faria toda tecnologia parecer mais rara do que é."""
    jobs = [_dict_job("remoto", ["aws"]) for _ in range(5)] + \
           [_dict_job("remoto", [], desc="") for _ in range(50)]
    m = skills.analyze(jobs, TAX)
    assert m["amostra"]["com_descricao"] == 5 and m["amostra"]["total"] == 55
    assert m["ranking"][0]["pct"] == 100


def test_catalogo_vai_junto_para_o_painel_recontar():
    m = skills.analyze([_dict_job("remoto", ["aws"])], TAX)
    assert m["catalogo"]["aws"] == {"nome": "AWS", "grupo": "Nuvem"}


def test_sem_taxonomia_nao_quebra():
    assert skills.analyze([_dict_job("remoto", [])], {}) == {}
    assert skills.extract("Python", {}) == []


# --- taxonomia real ---------------------------------------------------------
def test_skills_yaml_do_repo_e_valido():
    tax = skills.load_taxonomy(ROOT)
    habs = tax["habilidades"]
    assert len(habs) > 100
    nomes = [v["nome"] for v in habs.values()]
    assert len(nomes) == len(set(nomes)), "dois itens com o mesmo nome no ranking"
    for chave, v in habs.items():
        assert v.get("termos") and v.get("nome") and v.get("grupo"), chave
        assert "tenho" not in v, "o ranking não é filtrado pelo perfil"


# Trecho do anúncio "Profissional Fullstack (IA/Javascript) Trainee/Júnior", da
# Luby. Com a taxonomia antiga ele virava "Front-end" e "JavaScript/TS", e React,
# NestJS, PostgreSQL, Prisma, pgvector, Jest, n8n e Cursor não eram medidos.
LUBY = """
Desenvolver e evoluir interfaces responsivas em React e APIs escaláveis em NestJS.
Projetar e manter endpoints REST bem estruturados (respeitando camadas, DTOs).
Modelagem e evolução de schemas relacionais (PostgreSQL), utilização de ORMs
(Prisma/TypeORM) e escrita de queries otimizadas. Participar ativamente de code reviews.
Garantir versionamento e colaboração via Git (pull requests, conventional commits).
Integrar APIs de LLMs de ponta (Anthropic Claude, OpenAI, etc.) em fluxos operacionais.
Construir e manter pipelines RAG: ingestão de dados, estratégias de chunking, geração
de embeddings e consulta em bancos vetoriais (pgvector).
Criar automações combinando ferramentas no-code/low-code (n8n, Make) com scripts em Node.js.
Utilizar ferramentas de IA no workflow diário (Claude Code, Cursor) e aplicar técnicas de
prompt engineering. Escrever testes unitários e de integração (Jest).
JavaScript/TypeScript: domínio sólido de ES6+. Inglês técnico.
Familiaridade com arquiteturas RAG (chunking, vector stores, busca semântica).
Experiência com pgvector ou bancos vetoriais (Pinecone, Weaviate).
Prática com frameworks como LangChain ou LangGraph. Noções de containers (Docker) e pipelines de CI/CD.
"""


def test_vaga_real_da_luby_e_lida_tecnologia_por_tecnologia():
    achadas = set(skills.extract(LUBY, skills.load_taxonomy(ROOT)))
    esperadas = {"react", "nestjs", "rest", "postgresql", "prisma", "typeorm", "code_review", "git",
                 "llm", "claude", "openai", "rag", "embeddings", "banco_vetorial", "pgvector",
                 "n8n", "nodejs", "claude_code", "cursor", "prompt", "testes", "jest",
                 "javascript", "typescript", "ingles", "pinecone", "weaviate", "langchain",
                 "langgraph", "docker", "cicd"}
    assert esperadas <= achadas, f"faltaram: {sorted(esperadas - achadas)}"


@pytest.mark.parametrize("texto,nao_deve", [
    ("We are looking for someone with solid experience", "solid"),
    ("You will excel at communication", "excel"),
    ("Make sure the rest of the team is aligned", "rest"),
    ("a lean team moving fast", "lean"),
    ("Sob o prisma do cliente", "prisma"),
    ("Informe seu DDD e telefone", "ddd"),
])
def test_palavras_comuns_nao_viram_tecnologia(texto, nao_deve):
    assert nao_deve not in skills.extract(texto, skills.load_taxonomy(ROOT))


@pytest.mark.parametrize("texto,esperado", [
    ("Experiência com SAP ECC e SAP EWM", "sap"),
    ("Conhecimento em Power BI e DAX", "powerbi"),
    ("Princípios SOLID e Clean Code", "solid"),
    ("Necessário inglês avançado", "ingles"),
])
def test_taxonomia_real_reconhece_termos_do_dia_a_dia(texto, esperado):
    assert esperado in skills.extract(texto, skills.load_taxonomy(ROOT))
