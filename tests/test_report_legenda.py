"""O relatório não pode prometer o que não entregou."""
from datetime import datetime

from vagas_monitor import report
from vagas_monitor.config import load_config
from vagas_monitor.models import Job


def _ctx(jobs, errors=None):
    return report.build_context(jobs, load_config(), datetime(2026, 9, 13, 8, 30), 7,
                               {"gupy": 10}, errors or {}, {"known_jobs": 0, "first_run": False})


def _job(fit=None, company="ACME", tags=None) -> Job:
    j = Job(source="gupy", title="Analista de Dados Júnior", company=company,
            url="https://g/1", city="Itajaí", workplace="hybrid",
            date_posted="2026-09-12", description="Python e SQL", tags=tags or [])
    j.category, j.categories, j.seniority = "dados", ["dados"], "junior"
    j.matched_city, j.score, j.fit = "Itajaí", 80, fit
    if fit is not None:
        j.fit_note = "Boa aderência ao perfil."
    return j


# --- estrela ----------------------------------------------------------------
def test_sem_avaliacao_a_estrela_nao_e_mencionada():
    ctx = _ctx([_job(), _job()])
    assert ctx["ai_count"] == 0
    md, html = report.render_markdown(ctx), report.render_html(ctx)
    assert "★" not in md
    assert "avaliação do Claude" not in md
    assert "avaliação do Claude" not in html
    assert 'value="fit"' not in html  # ordenar por nota não faz sentido sem nota


def test_com_avaliacao_a_legenda_diz_a_cobertura():
    ctx = _ctx([_job(fit=8), _job(), _job()])
    assert ctx["ai_count"] == 1
    md, html = report.render_markdown(ctx), report.render_html(ctx)
    assert "★8/10" in md
    assert "aplicada às 1 melhores vagas novas de um total de 3" in md
    assert "aplicada às 1 melhores vagas novas de um total de 3" in html
    assert 'value="fit"' in html


def test_falha_da_ia_aparece_no_relatorio():
    ctx = _ctx([_job()], errors={"claude": "HTTP 400: saldo insuficiente"})
    md, html = report.render_markdown(ctx), report.render_html(ctx)
    assert "Avaliação por IA" in md and "saldo insuficiente" in md
    assert "Avaliação por IA" in html


# --- empresa ----------------------------------------------------------------
def test_card_sem_empresa_diz_isso():
    ctx = _ctx([_job(company="")])
    md, html = report.render_markdown(ctx), report.render_html(ctx)
    assert "Empresa não informada" in md
    assert "Empresa não informada" in html  # o painel resolve no JS


def test_empresa_inferida_do_site_e_marcada():
    ctx = _ctx([_job(company="Vem Ser Ixc", tags=["empresa-inferida"])])
    md = report.render_markdown(ctx)
    assert "Vem Ser Ixc (inferida)" in md
    assert "empresa-inferida" in report.render_html(ctx)


# --- compatibilidade do comando `render` ------------------------------------
def test_render_de_relatorio_antigo_nao_quebra(tmp_path):
    """`render` refaz rodadas passadas: um JSON sem as chaves novas tem de funcionar.

    O JSON de 13/09 foi gravado antes de `ai_count` existir, e derrubava o render
    com KeyError assim que a legenda condicional passou a lê-lo.
    """
    import json

    antigo = tmp_path / "2026-01-01.json"
    antigo.write_text(json.dumps({
        "run_date": "2026-01-01", "run_date_br": "01/01/2026", "run_time": "08:30",
        "lookback_days": 7, "cidades": ["Itajaí"], "categorias": {"dados": {"nome": "Dados", "prioridade": 2}},
        "by_category": {"dados": 1}, "by_city": {"Itajaí": 1},
        "jobs": [{"title": "Analista de Dados", "company": "ACME", "url": "https://g/1",
                  "source": "gupy", "score": 70, "is_new": True, "seniority": "junior",
                  "category": "dados", "matched_city": "Itajaí", "workplace": "hybrid",
                  "location": "Itajaí, SC", "date_posted": "2026-01-01", "age_days": 0,
                  "description": "", "reasons": [], "fit": None, "fit_note": "", "tags": []}],
    }, ensure_ascii=False), encoding="utf-8")

    ctx = report.load_context(antigo)
    assert ctx["ai_count"] == 0 and ctx["total"] == 1 and ctx["new_count"] == 1
    assert "Analista de Dados" in report.render_markdown(ctx)
    assert "Radar de Vagas" in report.render_html(ctx)


# --- ranking de tecnologias -------------------------------------------------
TAX = {"habilidades": {
    "sap": {"nome": "SAP", "grupo": "Corporativo", "termos": ["sap"]},
    "aws": {"nome": "AWS", "grupo": "Nuvem", "termos": ["aws"]},
    "docker": {"nome": "Docker", "grupo": "Nuvem", "termos": ["docker"]},
}}


def _mercado_ctx():
    """Contexto com o ranking já calculado, para exercitar a renderização."""
    from vagas_monitor import skills
    jl = [{"matched_city": "Itajaí", "workplace": "hybrid", "description": "d", "skills": ["sap"]}
          for _ in range(3)]
    jl += [{"matched_city": None, "workplace": "remote", "description": "d", "skills": ["aws", "docker"]}
           for _ in range(12)]
    jl += [{"matched_city": None, "workplace": "remote", "description": "d", "skills": ["aws"]}
           for _ in range(2)]
    ctx = _ctx([_job()])
    ctx["mercado"] = skills.analyze(jl, TAX)
    return ctx


def test_ranking_no_markdown_ordena_pela_contagem():
    md = report.render_markdown(_mercado_ctx())
    assert "## Tecnologias mais pedidas" in md
    sec = md.split("## Tecnologias mais pedidas")[1]
    assert sec.index("**AWS** | 14") < sec.index("**Docker** | 12") < sec.index("**SAP** | 3")


def test_markdown_nao_fala_em_lacuna_nem_perfil():
    md = report.render_markdown(_mercado_ctx())
    for termo in ("lacuna", "já domina", "Estude primeiro", "pedágio", "acessíveis"):
        assert termo not in md, termo


def test_painel_ganha_aba_de_ranking():
    html = report.render_html(_mercado_ctx())
    assert 'id="tabMercado"' in html and "Tecnologias mais pedidas" in html
    assert "renderMercado" in html
    assert '"catalogo"' in html  # o painel reconta com os filtros da barra lateral


def test_sem_mercado_o_painel_nao_mostra_aba():
    html = report.render_html(_ctx([_job()]))
    assert 'id="tabMercado"' not in html


def test_painel_corta_a_descricao_mas_o_json_guarda_inteira(tmp_path, monkeypatch):
    j = _job()
    j.description = "x" * 3000 + " AWS"
    ctx = _ctx([j])
    assert ctx["jobs"][0]["description"].endswith("AWS")
    html = report.render_html(ctx)
    assert "x" * 1300 not in html


def test_telegram_resume_as_mais_pedidas():
    from vagas_monitor.notify import telegram
    ctx = _mercado_ctx()
    ctx.update({"jobs": [], "new_count": 0, "total": 0, "run_date_br": "13/09/2026", "report_url": ""})
    msg = telegram.build_messages(ctx)[0]
    assert "Mais pedidas" in msg and "<b>AWS</b> 14" in msg
    assert len(msg) <= 4096


def test_email_resume_as_mais_pedidas():
    from vagas_monitor.notify import email_
    bloco = email_.build_mercado_html(_mercado_ctx())
    assert "Tecnologias mais pedidas" in bloco and "AWS" in bloco
    assert "<script" not in bloco


def test_render_reextrai_da_descricao_com_a_taxonomia_atual(tmp_path):
    """Mudou a taxonomia? `render` refaz o ranking sem recoletar as vagas."""
    import json
    p = tmp_path / "2026-09-13.json"
    p.write_text(json.dumps({
        "run_date": "2026-09-13", "run_date_br": "13/09/2026", "run_time": "08:30",
        "lookback_days": 7, "cidades": ["Itajaí"], "categorias": {},
        "by_category": {}, "by_city": {},
        "jobs": [{"title": "Dev", "company": "X", "url": "u", "source": "gupy", "score": 70,
                  "is_new": True, "seniority": "junior", "category": None, "matched_city": None,
                  "workplace": "remote", "location": "", "date_posted": None, "age_days": None,
                  "description": "Stack com Python, React e pgvector", "reasons": [], "fit": None,
                  "fit_note": "", "tags": [],
                  # gravado por uma versão anterior: chave que não existe mais e uma
                  # tecnologia que só aparecia depois do corte de 1200 caracteres
                  "skills": ["frontend", "aws"]} for _ in range(3)],
        "mercado": {},
    }, ensure_ascii=False), encoding="utf-8")
    ctx = report.load_context(p)
    chaves = set(ctx["jobs"][0]["skills"])
    assert {"python", "react", "pgvector", "aws"} <= chaves
    assert "frontend" not in chaves
    assert {r["nome"] for r in ctx["mercado"]["ranking"]} >= {"Python", "React", "pgvector", "AWS"}


def test_json_com_descricao_completa_reextrai_so_da_descricao(tmp_path):
    """Com a descrição inteira gravada, a chave antiga não tem por que sobreviver."""
    import json
    p = tmp_path / "2026-09-18.json"
    p.write_text(json.dumps({
        "run_date": "2026-09-18", "run_date_br": "18/09/2026", "run_time": "08:30",
        "lookback_days": 7, "cidades": [], "categorias": {}, "descricao_completa": True,
        "jobs": [{"title": "Dev", "company": "X", "url": "u", "source": "gupy", "score": 70,
                  "is_new": True, "seniority": "junior", "category": None, "matched_city": None,
                  "workplace": "remote", "location": "", "date_posted": None, "age_days": None,
                  "description": "Python", "reasons": [], "fit": None, "fit_note": "", "tags": [],
                  "skills": ["aws"]}],
    }, ensure_ascii=False), encoding="utf-8")
    assert report.load_context(p)["jobs"][0]["skills"] == ["python"]


def test_hidden_esconde_mesmo_com_display_de_autor():
    """A lista de vagas tem `display:flex`; sem a regra global, `hidden` perdia e a
    aba "O que estudar" mostrava as vagas empilhadas em cima do conteúdo."""
    assert "[hidden]{display:none!important}" in report.render_html(_ctx([_job()]))


def test_linhas_da_lista_tem_posicao_explicita_no_grid():
    """Com o posicionamento automático, a estatística tomava a coluna do meio e o
    nome da tecnologia era espremido e cortado na coluna estreita da direita."""
    html = report.render_html(_mercado_ctx())
    assert ".rrow .body{grid-column:2;grid-row:1" in html
    assert ".rrow .stat{grid-column:3;grid-row:1/span 2" in html


def test_arquivos_gerados_sempre_em_lf(tmp_path, monkeypatch):
    """No Windows o padrão é CRLF; o robô do GitHub gera LF. Sem forçar, cada rodada
    local virava um diff do arquivo inteiro: 25 mil linhas para mudar poucas."""
    monkeypatch.setattr(report, "ROOT", tmp_path)
    paths = report.write_all(_mercado_ctx(), load_config())
    for nome, caminho in paths.items():
        assert b"\r\n" not in caminho.read_bytes(), f"{nome} saiu com CRLF"
