"""Gupy: formato novo da API (portal.gupy.io/api/job-search/jobs)."""
from datetime import date

from vagas_monitor.sources import gupy


def _vaga(id_, wp, publicada=None, **extra):
    return {
        "id": id_, "name": "Analista de Dados", "careerPageName": "ACME",
        "jobUrl": f"https://acme.gupy.io/job/x{id_}?jobBoardSource=gupy_portal",
        "publishedDate": (publicada or date.today().isoformat()) + "T12:00:00.000Z",
        "workplaceType": wp, "city": "Itajaí", "state": "Santa Catarina",
        "description": "<p>SQL e Python</p>", "type": "vacancy_type_effective", **extra,
    }


def test_endpoint_e_o_do_portal_novo():
    # o antigo (employability-portal.gupy.io) devolve 404 desde o início de 10/2026
    assert gupy.BASE == "https://portal.gupy.io/api/job-search/jobs"


def test_remoto_vem_de_workplace_type_e_nao_de_is_remote_work():
    # a resposta nova não traz `isRemoteWork`; sem isso toda vaga remota virava presencial
    remota, presencial = gupy._to_job(_vaga(1, "remote")), gupy._to_job(_vaga(2, "on-site"))
    assert remota.remote and remota.workplace == "remote"
    assert not presencial.remote and presencial.workplace == "onsite"
    assert remota.external_id == "gupy:1"


def test_busca_de_remotas_filtra_por_workplace_type(monkeypatch):
    # `isRemoteWork=true` deixou de filtrar: a busca devolvia presencial e híbrida junto
    chamadas = []

    def falso(params):
        chamadas.append(params)
        return [_vaga(len(chamadas), "remote")] if params.get("jobName") == "dados" else []

    monkeypatch.setattr(gupy, "_page", falso)
    monkeypatch.setattr(gupy.time, "sleep", lambda s: None)

    jobs = gupy.collect(["dados"], lookback_days=7)

    remotas = [p for p in chamadas if p.get("jobName") == "dados"]
    assert remotas and all(p.get("workplaceType") == "remote" for p in remotas)
    assert not any("isRemoteWork" in p for p in chamadas)
    assert any(j.remote for j in jobs)
