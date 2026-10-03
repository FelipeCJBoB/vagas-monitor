"""Testa o pipeline ponta a ponta com fontes falsas (sem rede)."""
import json
from datetime import date

from vagas_monitor import pipeline, report
from vagas_monitor.config import load_config
from vagas_monitor.models import Job


def _fake_jobs():
    return [
        Job(source="gupy", title="Analista de Dados Júnior", company="Portonave", url="https://g/1",
            city="Navegantes", state="Santa Catarina", workplace="hybrid", date_posted="2026-09-03",
            description="Python, SQL, Power BI e Excel. Vaga júnior."),
        Job(source="indeed", title="Analista de Dados Junior", company="PORTONAVE", url="https://i/1",
            location="Navegantes, SC, BR", date_posted="2026-09-03", description="curta"),  # duplicata entre fontes
        Job(source="linkedin", title="Engenheiro de Dados Sênior", company="WEG", url="https://li/2",
            location="Jaraguá do Sul, SC", date_posted="2026-09-01"),
        Job(source="linkedin", title="Cientista de Dados (Remoto)", company="Nubank", url="https://li/3",
            location="São Paulo, SP", date_posted="2026-09-02"),
        Job(source="indeed", title="Analista de Marketing", company="X", url="https://i/4",
            location="Blumenau, SC, BR", description="Redes sociais"),  # fora das categorias
        Job(source="gupy", title="Desenvolvedor Full Stack", company="Y", url="https://g/5",
            city="Florianópolis", state="Santa Catarina", workplace="onsite"),  # fora das cidades
    ]


def test_id_distingue_vagas_do_indeed_pela_query_string():
    a = Job(source="indeed", title="A", company="X", url="https://br.indeed.com/viewjob?jk=111")
    b = Job(source="indeed", title="B", company="Y", url="https://br.indeed.com/viewjob?jk=222")
    assert a.id != b.id
    assert len(pipeline.dedupe([a, b])) == 2


def test_dedupe_prefere_descricao_maior():
    out = pipeline.dedupe(_fake_jobs())
    titles = [j.title for j in out]
    assert titles.count("Analista de Dados Júnior") == 1
    assert "Analista de Dados Junior" not in titles  # a versão do Indeed (descrição curta) foi descartada


def test_annotate_escopo(monkeypatch):
    cfg = load_config()
    today = date(2026, 9, 5)
    jobs = [j for j in pipeline.dedupe(_fake_jobs()) if pipeline.annotate(j, cfg, today)]
    titles = {j.title for j in jobs}
    assert "Analista de Dados Júnior" in titles
    assert "Engenheiro de Dados Sênior" in titles
    assert "Cientista de Dados (Remoto)" in titles
    assert "Analista de Marketing" not in titles
    assert "Desenvolvedor Full Stack" not in titles
    top = max(jobs, key=lambda j: j.score)
    assert top.title == "Analista de Dados Júnior" and top.matched_city == "Navegantes"


def test_run_end_to_end(monkeypatch, tmp_path):
    cfg = load_config()
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "collect_all", lambda cfg, lb, errors, skip=(): (_fake_jobs(), {"gupy": 2, "indeed": 2, "linkedin": 2}))
    monkeypatch.setattr(pipeline.linkedin, "fetch_description", lambda j: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)

    s1 = pipeline.run(force=True)
    assert s1["in_scope"] == 3 and s1["new"] == 3 and s1["lookback_days"] == cfg["first_run_lookback_days"]
    assert (tmp_path / "reports" / "LATEST.md").exists() and (tmp_path / "docs" / "index.html").exists()
    md = (tmp_path / "reports" / "LATEST.md").read_text(encoding="utf-8")
    assert "3 vagas novas" in md and "Navegantes" in md
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Radar de Vagas" in html and "Portonave" in html

    # 2ª rodada no mesmo dia: cadência bloqueia
    s2 = pipeline.run()
    assert s2["skipped"]
    # forçada: nada é novo
    s3 = pipeline.run(force=True)
    assert s3["new"] == 0 and s3["in_scope"] == 3
    state = json.loads((tmp_path / "state" / "seen.json").read_text(encoding="utf-8"))
    assert len(state["jobs"]) == 3


def test_falha_da_ia_nao_derruba_a_rodada(monkeypatch, tmp_path):
    """A avaliação por IA é opcional: uma exceção nela não pode custar a rodada inteira.

    Antes desta proteção, qualquer erro do SDK descartava 8 minutos de coleta,
    o relatório, o estado e a notificação.
    """
    import sys
    import types

    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "collect_all", lambda cfg, lb, errors, skip=(): (_fake_jobs(), {"gupy": 6}))
    monkeypatch.setattr(pipeline.linkedin, "fetch_description", lambda j: False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)

    def explode(*a, **k):
        raise TypeError("parâmetro inválido no SDK")

    monkeypatch.setitem(sys.modules, "vagas_monitor.enrich", types.SimpleNamespace(enrich=explode))

    s = pipeline.run(force=True)

    assert not s["skipped"]
    assert s["in_scope"] == 3
    assert s["ai_evaluated"] == 0
    assert "TypeError" in s["ai_error"]
    assert "ia" in s["errors"]
    # o que importa: relatório e estado sobreviveram
    assert (tmp_path / "reports" / "LATEST.md").exists()
    assert (tmp_path / "docs" / "index.html").exists()
    assert (tmp_path / "state" / "seen.json").exists()
    # e o leitor fica sabendo que faltou a nota da IA
    assert "Avaliação por IA" in (tmp_path / "reports" / "LATEST.md").read_text(encoding="utf-8")


def test_falha_de_notificacao_aparece_no_relatorio_e_no_codigo_de_saida(monkeypatch, tmp_path):
    """Telegram com token revogado ficou 10 dias mudo com o passo do Actions verde.

    A rodada continua valendo (relatório e estado gravados), mas o motivo vai para o
    topo do relatório e `cmd_run` devolve erro para o job ficar vermelho.
    """
    from types import SimpleNamespace

    from vagas_monitor import __main__ as cli
    from vagas_monitor.notify import telegram

    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "collect_all", lambda cfg, lb, errors, skip=(): (_fake_jobs(), {"gupy": 6}))
    monkeypatch.setattr(pipeline.linkedin, "fetch_description", lambda j: False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "revogado")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(telegram, "send_message", lambda token, chat, text: False)

    s = pipeline.run(force=True)

    assert s["sent"] == {"telegram": False}
    assert s["notify_failed"] == ["telegram"]
    assert (tmp_path / "state" / "seen.json").exists()
    assert "Telegram" in (tmp_path / "reports" / "LATEST.md").read_text(encoding="utf-8")

    monkeypatch.setattr(pipeline, "run", lambda **k: s)
    args = SimpleNamespace(force=True, dry_run=False, no_notify=False, lookback=None, config=None, skip=None)
    assert cli.cmd_run(args) == 1


def test_fonte_que_volta_vazia_vira_aviso(monkeypatch):
    """A Gupy ficou em zero vagas por dias (API trocada) e só havia um warning no log."""
    monkeypatch.setattr(pipeline.gupy, "collect", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.indeed, "collect", lambda *a, **k: _fake_jobs()[:1])
    monkeypatch.setattr(pipeline.linkedin, "collect", lambda *a, **k: _fake_jobs()[1:2])
    errors: dict = {}

    _, counts = pipeline.collect_all(load_config(), 7, errors)

    assert counts["gupy"] == 0 and counts["indeed"] == 1
    assert list(errors) == ["gupy"]
    assert "nenhuma vaga" in errors["gupy"]


def test_aviso_de_fonte_chega_no_telegram_e_no_email_mas_o_da_ia_nao():
    from vagas_monitor.notify import email_, fontes_com_problema, telegram

    ctx = json.loads(json.dumps({
        "jobs": [], "categorias": {}, "total": 0, "lookback_days": 7, "run_date_br": "03/10/2026",
        "new_count": 0, "report_url": "",
        "errors": {"gupy": "nenhuma vaga coletada", "ia": "Gemini: 503", "telegram": "envio falhou"},
    }))

    assert fontes_com_problema(ctx) == {"Gupy": "nenhuma vaga coletada"}
    assert "Fonte com problema" in telegram.build_messages(ctx)[0]
    assert "Gupy" in telegram.build_messages(ctx)[0]
    assert "Gemini" not in telegram.build_messages(ctx)[0]
    assert "Fonte com problema" in email_.build_html(ctx)

    sem_erro = dict(ctx, errors={})
    assert "Fonte com problema" not in telegram.build_messages(sem_erro)[0]
    assert "Fonte com problema" not in email_.build_html(sem_erro)
