"""Identidade da vaga no ATS de origem, extraída do link de candidatura."""
import pytest

from vagas_monitor.ats import company_from_url, company_slug, external_id, gupy_job_id
from vagas_monitor.dedupe import merge_duplicates, same_job
from vagas_monitor.models import Job

# a MESMA vaga, como a Gupy e o Indeed publicam o link (o token carrega a origem)
GUPY = "https://vemserixcsoft.gupy.io/job/eyJqb2JJZCI6MTIzNzM4MzUsInNvdXJjZSI6Imd1cHlfcG9ydGFsIn0="
INDEED = "https://vemserixcsoft.gupy.io/job/eyJqb2JJZCI6MTIzNzM4MzUsInNvdXJjZSI6ImluZGVlZCJ9?jobBoardSource=indeed"


def test_mesmo_id_em_fontes_diferentes():
    assert gupy_job_id(GUPY) == gupy_job_id(INDEED) == 12373835
    assert external_id(GUPY) == external_id(INDEED) == "gupy:12373835"


def test_token_sem_padding():
    """O Indeed corta o '=' final; base64 sem padding tem de decodificar igual."""
    assert gupy_job_id(INDEED.split("?")[0].rstrip("=")) == 12373835


@pytest.mark.parametrize("url", [
    None, "", "https://br.indeed.com/viewjob?jk=abc", "https://www.linkedin.com/jobs/view/4463365814",
    "https://empresa.gupy.io/job/naoEhBase64!!", "https://empresa.gupy.io/job/aGVsbG8=",  # json inválido
])
def test_urls_sem_id_nao_quebram(url):
    assert gupy_job_id(url) is None
    assert external_id(url) is None


def test_empresa_a_partir_do_subdominio():
    assert company_slug("https://stlflix.vagas.solides.com.br/vaga/916977") == "stlflix"
    assert company_from_url("https://vem-ser-ixc.gupy.io/job/x") == "Vem Ser Ixc"
    assert company_from_url("https://br.indeed.com/job/desenvolvedor-full-stack-fcd") == ""


def test_subdominio_generico_nao_vira_empresa():
    assert company_slug("https://www.gupy.io/job/x") is None
    assert company_from_url("https://vagas.solides.com.br/vaga/1") == ""


# --- efeito na deduplicação -------------------------------------------------
def _job(source, title, company, url, ext=None, description=""):
    return Job(source=source, title=title, company=company, url=url,
               external_id=ext, description=description)


def test_id_do_ats_funde_titulos_divergentes():
    """Com id igual, títulos diferentes não impedem a fusão."""
    a = _job("gupy", "Desenvolvedor de Sistemas Sênior - IXC ACS", "IXC Soft",
             "https://g/1", external_id(GUPY), description="completa")
    b = _job("indeed", "Desenvolvedor de Sistemas Senior (Chapecó-SC)", "",
             "https://i/1", external_id(INDEED))
    assert same_job(a, b)
    out = merge_duplicates([a, b])
    assert len(out) == 1 and out[0].company == "IXC Soft"


def test_ids_diferentes_nunca_fundem():
    """Duas vagas da mesma empresa com título idêntico, mas anúncios distintos."""
    a = _job("gupy", "Analista de Dados Júnior", "ACME", "https://g/1", "gupy:111")
    b = _job("indeed", "Analista de Dados Júnior", "ACME", "https://i/1", "gupy:222")
    assert not same_job(a, b)
    assert len(merge_duplicates([a, b])) == 2


def test_id_sobrevive_a_fusao():
    """Se só a cópia descartada tinha o link do ATS, a mantida herda o id."""
    com_id = _job("indeed", "Analista de Dados Júnior", "ACME", "https://i/1", "gupy:111")
    sem_id = _job("gupy", "Analista de Dados Júnior", "ACME", "https://g/1", None, description="completa")
    out = merge_duplicates([com_id, sem_id])
    assert len(out) == 1
    assert out[0].external_id == "gupy:111"


def test_uma_fonte_sem_id_cai_no_casamento_por_tokens():
    a = _job("gupy", "Líder de Dados e Analytics", "WeScale", "https://g/1", "gupy:111")
    b = _job("indeed", "Líder de Dados e Analytics", "WeScale SAS", "https://i/1", None)
    assert same_job(a, b)
