"""Deduplicação tolerante: casos reais observados na rodada de 11/09/2026."""
from datetime import date

import pytest

from vagas_monitor.dedupe import merge_duplicates, same_job
from vagas_monitor.models import Job
from vagas_monitor.state import State


def job(title, company, source="gupy", url=None, description="") -> Job:
    return Job(source=source, title=title, company=company,
               url=url or f"https://{source}/{abs(hash(title + company)) % 10**6}",
               description=description)


# --- deve fundir ------------------------------------------------------------
def test_prefixo_de_marca_no_titulo():
    """Atento TI x Escalada: mesma vaga, republicada com prefixo e outra marca."""
    a = job("Engenheiro(a) de Agentes de IA (AI Agent Engineer) - Remoto", "Atento TI")
    b = job("ATENTO ESCALADA - Engenheiro(a) de Agentes de IA (AI Agent Engineer) - Remoto", "Escalada")
    assert same_job(a, b)


def test_razao_social_diferente():
    """Grupo Malwee x Malwee Malhas: um token de empresa contido no outro."""
    a = job("Analista de Imagem Junior - Foco em Styling & IA", "Grupo Malwee", "linkedin")
    b = job("Analista de Imagem Junior - Foco em Styling & IA", "Malwee Malhas", "indeed")
    assert same_job(a, b)


def test_sufixo_societario():
    a = job("Líder de Dados e Analytics", "WeScale")
    b = job("Líder de Dados e Analytics", "WeScale SAS", "indeed")
    assert same_job(a, b)


def test_empresa_ausente_numa_fonte():
    a = job("Desenvolvedor(a) Back-end e Dados", "", "indeed")
    b = job("Desenvolvedor(a) Back-end e Dados", "Jobbol", "linkedin")
    assert same_job(a, b)


def test_codigo_de_referencia_ignorado():
    a = job("Python Junior Developer - Remote Work / REF#283517", "BairesDev")
    b = job("Python Junior Developer", "BairesDev", "indeed")
    assert same_job(a, b)


# --- NÃO deve fundir --------------------------------------------------------
def test_titulo_generico_em_empresas_diferentes():
    """Risco principal do casamento tolerante: dois anúncios distintos com o mesmo título."""
    a = job("Desenvolvedor Full Stack", "MULTITHERM", "indeed")
    b = job("Desenvolvedor Full Stack", "Agromai", "indeed")
    assert not same_job(a, b)


def test_vagas_irmas_na_mesma_empresa():
    """Ultra LIMS publicou as duas no mesmo dia; são cargos diferentes."""
    a = job("Analista de Dados Júnior (SQL) - Joinville/SC - Híbrido", "Ultra LIMS", "indeed")
    b = job("Analista de Banco de Dados Júnior (DBA) - Joinville/SC - Híbrido", "Ultra LIMS", "indeed")
    assert not same_job(a, b)


def test_niveis_diferentes():
    a = job("Desenvolvedor Full Stack", "ACME")
    b = job("Desenvolvedor Full Stack Pleno", "ACME")
    assert not same_job(a, b)


def test_titulo_curto_nao_funde_por_contencao():
    """"Analista de Dados" contido em "Analista de Dados e Processos" não basta."""
    a = job("Analista de Dados", "ACME")
    b = job("Analista de Dados e Processos Comerciais", "ACME")
    assert not same_job(a, b)  # só 2 tokens no menor


def test_empresa_ausente_e_titulo_curto():
    a = job("Analista de BI", "", "indeed")
    b = job("Analista de BI", "Empresa X", "gupy")
    assert not same_job(a, b)  # 2 tokens: específico demais para arriscar


# --- merge_duplicates -------------------------------------------------------
def test_merge_mantem_a_copia_com_descricao_e_guarda_alias():
    a = job("Engenheiro(a) de Agentes de IA (AI Agent Engineer) - Remoto", "Atento TI",
            description="Descrição completa da vaga com requisitos.")
    b = job("ATENTO ESCALADA - Engenheiro(a) de Agentes de IA (AI Agent Engineer) - Remoto", "Escalada")
    out = merge_duplicates([b, a])
    assert len(out) == 1
    mantida = out[0]
    assert mantida.company == "Atento TI"          # a que tem descrição vence
    assert b.dedup_key in mantida.aliases


def test_merge_preserva_vagas_distintas():
    jobs = [
        job("Analista de Dados Júnior (SQL) - Joinville/SC", "Ultra LIMS"),
        job("Analista de Banco de Dados Júnior (DBA) - Joinville/SC", "Ultra LIMS"),
        job("Desenvolvedor Full Stack", "MULTITHERM"),
        job("Desenvolvedor Full Stack", "Agromai"),
    ]
    assert len(merge_duplicates(jobs)) == 4


def test_merge_e_estavel_independente_da_ordem():
    a = job("Cientista de Dados Pleno - Remoto", "Nubank")
    b = job("NUBANK TALENTOS - Cientista de Dados Pleno - Remoto", "Nubank Talentos")
    assert merge_duplicates([a, b])[0].id == merge_duplicates([b, a])[0].id


# --- integração com o estado ------------------------------------------------
def test_alias_evita_reanuncio_quando_a_copia_sobrevivente_troca(tmp_path):
    """Rodada 1 mantém a cópia da Atento; rodada 2 mantém a da Escalada.

    Sem os aliases no estado, a rodada 2 anunciaria a mesma vaga como nova.
    """
    atento = job("Engenheiro(a) de Agentes de IA - Remoto", "Atento TI",
                 url="https://atentoti.gupy.io/job/1", description="texto longo")
    escalada = job("ATENTO ESCALADA - Engenheiro(a) de Agentes de IA - Remoto", "Escalada",
                   url="https://escalada.gupy.io/job/2")

    st = State(tmp_path / "seen.json")
    r1 = merge_duplicates([atento, escalada])[0]
    assert st.is_new(r1)
    st.mark(r1, date(2026, 9, 11))
    st.save()

    # rodada 2: agora a cópia da Escalada é a que traz descrição
    atento2 = job("Engenheiro(a) de Agentes de IA - Remoto", "Atento TI", url="https://atentoti.gupy.io/job/1")
    escalada2 = job("ATENTO ESCALADA - Engenheiro(a) de Agentes de IA - Remoto", "Escalada",
                    url="https://escalada.gupy.io/job/2", description="texto longo agora aqui")
    st2 = State(tmp_path / "seen.json")
    r2 = merge_duplicates([atento2, escalada2])[0]
    assert r2.company == "Escalada"
    assert not st2.is_new(r2)


def test_state_antigo_sem_campo_aliases_continua_funcionando(tmp_path):
    p = tmp_path / "seen.json"
    p.write_text('{"last_run": "2026-09-11T08:30:00", "jobs": {"abc": '
                 '{"key": "analista de dados|acme", "first_seen": "2026-09-11", "last_seen": "2026-09-11"}}}',
                 encoding="utf-8")
    st = State(p)
    assert not st.is_new(job("Analista de Dados", "ACME"))
    assert st.is_new(job("Engenheiro de Dados", "ACME"))


# --- regressões dos falsos positivos encontrados no replay de 11/09 ---------
def test_nome_generico_de_empresa_nao_vira_empresa_ausente():
    """"Oportunidades" é o nome da página de carreiras, não um campo vazio.

    Antes do fallback em company_tokens ele era reduzido a conjunto vazio, e a vaga
    fundia com a de outra empresa que tivesse título parecido.
    """
    a = job("CIENTISTA DE DADOS JÚNIOR", "Oportunidades")
    b = job("Processo Seletivo 2026 - Cientista de Dados Júnior", "Elogroup", "indeed")
    assert not same_job(a, b)


def test_niveis_romanos_distinguem_vagas():
    """"Especialista I" e "Especialista II": o marcador de nível tem 1 caractere."""
    a = job("Pessoa Desenvolvedora Backend Python Especialista I", "Grupo Boticário")
    b = job("Pessoa Desenvolvedora Backend Python Especialista II", "Grupo Boticário")
    assert not same_job(a, b)


def test_mesma_vaga_da_mesma_empresa_com_stack_extra_funde():
    """Mesmo nível e mesma squad, só a stack citada muda: é o mesmo anúncio."""
    a = job("Pessoa Desenvolvedora BackEnd Python/ NodeJs Especialista I (Venda Direta)", "Grupo Boticário")
    b = job("Pessoa Desenvolvedora Backend Python Especialista I (Venda Direta)", "Grupo Boticário")
    assert same_job(a, b)


def test_replay_da_rodada_real_de_11_09(tmp_path):
    """Guarda o resultado medido sobre os dados reais: 120 cards viram 114."""
    import json
    import pathlib

    origem = pathlib.Path(__file__).resolve().parent.parent / "reports" / "2026-09-11.json"
    if not origem.exists():
        pytest.skip("relatório de referência não está no checkout")
    ctx = json.loads(origem.read_text(encoding="utf-8"))
    jobs = [Job(source=j["source"], title=j["title"], company=j["company"], url=j["url"],
                description=j["description"]) for j in ctx["jobs"]]
    out = merge_duplicates(jobs)
    assert len(jobs) == 120
    assert len(out) == 114
    fundidas = {a.split("|")[1] for j in out for a in j.aliases}
    assert "atento ti" in fundidas          # o caso que motivou a correção
    assert "grupo malwee" in fundidas
    assert "wescale sas" in fundidas
    assert "elogroup" not in fundidas       # empresa distinta: não pode fundir
