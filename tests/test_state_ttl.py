"""Janela de validade da chave título+empresa em `State.is_new`.

Sem a janela, uma posição reaberta meses depois na mesma empresa nunca era
anunciada: bastava o par ter aparecido uma vez dentro do período de retenção.
"""
from datetime import date

from vagas_monitor.models import Job
from vagas_monitor.state import State


def job(title="Analista de Dados", company="ACME", url="https://g/1", ext=None) -> Job:
    return Job(source="gupy", title=title, company=company, url=url, external_id=ext)


def test_vaga_reaberta_depois_da_janela_volta_a_ser_nova(tmp_path):
    st = State(tmp_path / "seen.json", key_ttl_days=30)
    st.mark(job(url="https://g/antiga"), date(2026, 1, 10))
    st.save()

    outra_url = job(url="https://g/nova")
    st2 = State(tmp_path / "seen.json", key_ttl_days=30)
    assert not st2.is_new(outra_url, date(2026, 2, 1))   # 22 dias: ainda é o mesmo anúncio
    assert st2.is_new(outra_url, date(2026, 3, 15))      # 64 dias: a empresa reabriu a posição


def test_mesma_url_nunca_e_nova_independente_do_tempo(tmp_path):
    """O id vem da URL: se é literalmente o mesmo anúncio, não reanuncia nunca."""
    st = State(tmp_path / "seen.json", key_ttl_days=30)
    j = job()
    st.mark(j, date(2026, 1, 10))
    assert not st.is_new(j, date(2027, 1, 10))


def test_janela_renova_a_cada_rodada(tmp_path):
    """Vaga que segue no ar é revista toda rodada, então a data não envelhece."""
    st = State(tmp_path / "seen.json", key_ttl_days=30)
    st.mark(job(url="https://g/a"), date(2026, 1, 10))
    st.mark(job(url="https://g/a"), date(2026, 2, 5))
    st.mark(job(url="https://g/a"), date(2026, 3, 1))
    assert not st.is_new(job(url="https://g/outra"), date(2026, 3, 20))


def test_identidade_do_ats_tambem_suprime(tmp_path):
    """Mesma vaga, URLs diferentes por fonte: o id do ATS evita o anúncio duplicado."""
    st = State(tmp_path / "seen.json", key_ttl_days=30)
    st.mark(job(title="Dev Sênior IXC", company="IXC Soft",
                url="https://gupy/1", ext="gupy:12373835"), date(2026, 9, 11))
    st.save()

    pelo_indeed = job(title="Desenvolvedor de Sistemas Senior", company="",
                      url="https://indeed/9", ext="gupy:12373835")
    st2 = State(tmp_path / "seen.json", key_ttl_days=30)
    assert not st2.is_new(pelo_indeed, date(2026, 9, 13))


def test_estado_antigo_sem_datas_por_chave_e_migrado(tmp_path):
    """Formato anterior não tinha `ext_keys`; a data sai de `last_seen` da vaga."""
    p = tmp_path / "seen.json"
    p.write_text('{"last_run": "2026-09-11T08:30:00", "jobs": {"abc": {'
                 '"key": "analista de dados|acme", "first_seen": "2026-06-01", '
                 '"last_seen": "2026-09-11"}}}', encoding="utf-8")
    st = State(p, key_ttl_days=30)
    assert not st.is_new(job(url="https://g/outra"), date(2026, 9, 13))
    assert st.is_new(job(url="https://g/outra"), date(2026, 12, 1))


def test_ttl_configuravel(tmp_path):
    st = State(tmp_path / "seen.json", key_ttl_days=5)
    st.mark(job(url="https://g/a"), date(2026, 9, 1))
    assert st.is_new(job(url="https://g/b"), date(2026, 9, 10))
