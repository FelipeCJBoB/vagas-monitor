from datetime import date, datetime, timedelta

from vagas_monitor.models import Job
from vagas_monitor.notify import telegram
from vagas_monitor.state import State


def test_state_due_e_novidade(tmp_path):
    st = State(tmp_path / "seen.json")
    assert st.first_run and st.due(5)
    j = Job(source="gupy", title="Analista de Dados Jr", company="ACME", url="https://g/1")
    assert st.is_new(j)
    st.mark(j, date(2026, 9, 5))
    assert not st.is_new(j)
    # mesma vaga em outra fonte (URL diferente) também não é nova
    j2 = Job(source="linkedin", title="Analista de Dados JR", company="acme", url="https://li/9")
    assert not st.is_new(j2)
    st.set_last_run(datetime(2026, 9, 5, 8, 0))
    st.save()

    st2 = State(tmp_path / "seen.json")
    assert not st2.first_run
    assert not st2.due(5, datetime(2026, 9, 8, 8, 0))
    assert st2.due(5, datetime(2026, 9, 10, 3, 0))  # tolerância de 6h
    assert not st2.is_new(j2)


def test_state_prune(tmp_path):
    st = State(tmp_path / "seen.json")
    j = Job(source="gupy", title="X", company="Y", url="https://g/2")
    st.mark(j, date(2026, 1, 1))
    assert st.prune(keep_days=120, today=date(2026, 9, 5)) == 1
    assert st.is_new(j)


def _ctx(n_new):
    jobs = [{"is_new": True, "score": 90 - i, "fit": 8 if i == 0 else None, "fit_note": "Boa aderência" if i == 0 else "",
             "url": f"https://x/{i}", "title": f"Vaga <{i}> & Cia", "company": "Empresa", "matched_city": "Itajaí",
             "workplace": "hybrid", "location": "Itajaí, SC", "seniority": "junior", "category": "dados"} for i in range(n_new)]
    return {"run_date_br": "05/09/2026", "total": n_new, "new_count": n_new, "lookback_days": 7,
            "categorias": {"dados": {"nome": "Dados"}}, "jobs": jobs, "report_url": "https://r"}


def test_telegram_mensagem_escapa_html_e_quebra():
    msgs = telegram.build_messages(_ctx(3), top_n=15)
    assert len(msgs) == 1
    assert "Vaga &lt;0&gt; &amp; Cia" in msgs[0]
    assert "★8/10" in msgs[0] and "Relatório completo" in msgs[0]
    big = telegram.build_messages(_ctx(120), top_n=120)
    assert len(big) > 1 and all(len(m) <= 4096 for m in big)


def test_telegram_sem_novas():
    msgs = telegram.build_messages(_ctx(0))
    assert "Nenhuma vaga nova" in msgs[0]


def test_write_env_atualiza_sem_duplicar(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\nTELEGRAM_CHAT_ID=\nB=2\n", encoding="utf-8")
    telegram.write_env(p, "TELEGRAM_CHAT_ID", "123")
    telegram.write_env(p, "NOVA", "x")
    txt = p.read_text(encoding="utf-8")
    assert txt.count("TELEGRAM_CHAT_ID=") == 1 and "TELEGRAM_CHAT_ID=123" in txt and "NOVA=x" in txt
