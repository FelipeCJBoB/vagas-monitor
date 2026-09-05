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
