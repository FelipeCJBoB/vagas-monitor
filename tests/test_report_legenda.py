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


# --- seção "O que o mercado cobra" ------------------------------------------
def _mercado_ctx(comparavel=True):
    """Contexto com mapa de mercado já calculado, para exercitar a renderização."""
    from vagas_monitor import skills
    tax = {"habilidades": {
        "sap": {"nome": "SAP", "grupo": "Corporativo", "tenho": "sim", "termos": ["sap"]},
        "aws": {"nome": "AWS", "grupo": "Nuvem", "tenho": "nao", "termos": ["aws"]},
        "docker": {"nome": "Docker", "grupo": "Nuvem", "tenho": "parcial", "termos": ["docker"]},
    }, "min_ocorrencias": 2}
    n_reg = 12 if comparavel else 3
    jl = [{"matched_city": "Itajaí", "workplace": "hybrid", "seniority": "junior",
           "description": "d", "skills": ["sap"]} for _ in range(n_reg)]
    jl += [{"matched_city": None, "workplace": "remote", "seniority": "junior",
            "description": "d", "skills": ["aws", "docker"]} for _ in range(12)]
    ctx = _ctx([_job()])
    ctx["mercado"] = skills.analyze(jl, tax)
    return ctx


def test_secao_de_mercado_no_markdown():
    md = report.render_markdown(_mercado_ctx())
    assert "## O que o mercado cobra" in md
    assert "### Estude primeiro" in md and "### Onde está cada lacuna" in md
    assert "Mapa completo" in md  # recolhido em <details>, mas presente
    assert "AWS" in md and "SAP" in md


def test_prioridade_ordena_lacuna_antes_do_que_ja_domina():
    md = report.render_markdown(_mercado_ctx())
    prio = md.split("### Estude primeiro")[1].split("### Onde está cada lacuna")[0]
    assert "AWS" in prio and "SAP" not in prio       # SAP já é domínio dele
    assert prio.index("AWS") < prio.index("Docker")  # lacuna antes de parcial


def test_amostra_pequena_vira_aviso_explicito():
    md = report.render_markdown(_mercado_ctx(comparavel=False))
    assert "Comparação entre os dois mercados suspensa" in md
    assert "amostra insuficiente" in md


def test_painel_ganha_aba_de_mercado():
    html = report.render_html(_mercado_ctx())
    assert 'id="tabMercado"' in html and "O que estudar" in html
    assert "renderMercado" in html
    assert '"mercado"' in html  # os dados vão no payload


def test_sem_mercado_o_painel_nao_mostra_aba():
    html = report.render_html(_ctx([_job()]))
    assert 'id="tabMercado"' not in html


def test_telegram_resume_o_que_estudar():
    from vagas_monitor.notify import telegram
    ctx = _mercado_ctx()
    ctx.update({"jobs": [], "new_count": 0, "total": 0, "run_date_br": "13/09/2026", "report_url": ""})
    msg = telegram.build_messages(ctx)[0]
    assert "Estudar primeiro" in msg and "AWS" in msg
    assert len(msg) <= 4096


def test_email_resume_o_que_estudar():
    from vagas_monitor.notify import email_
    bloco = email_.build_mercado_html(_mercado_ctx())
    assert "O que estudar primeiro" in bloco and "AWS" in bloco
    assert "<script" not in bloco


def test_veredito_nomeia_tecnologias_e_nao_familias():
    """O pedido original: não "Nuvem", mas QUAL tecnologia de nuvem.

    As duas conclusões que respondem "o que estudar" têm de trazer os itens
    concretos no título. A família aparece só como contexto na frase seguinte.
    """
    md = report.render_markdown(_mercado_ctx())
    pedagio = next(l for l in md.splitlines() if "Seu pedágio para o remoto" in l)
    titulo = pedagio.split(".")[0]                   # a parte antes do primeiro ponto
    assert "**AWS**" in titulo and "Nuvem" not in titulo
    diferencial = next(l for l in md.splitlines() if "Seu diferencial" in l)
    assert "**SAP**" in diferencial.split(".")[0]


def test_tabela_de_lacunas_poe_a_tecnologia_na_primeira_coluna():
    md = report.render_markdown(_mercado_ctx())
    tabela = md.split("### Onde está cada lacuna")[1].split("<details>")[0]
    cabecalho = next(l for l in tabela.splitlines() if l.startswith("| "))
    assert cabecalho.startswith("| Estude | Família")  # tecnologia antes da família
    linha_nuvem = next(l for l in tabela.splitlines() if "| Nuvem |" in l)
    assert linha_nuvem.startswith("| **AWS**") or linha_nuvem.startswith("| **Docker**")


def test_painel_usa_as_cores_de_serie_validadas():
    """Teal com o verde de status reprovava no validador (ΔE 8,7) e confundia
    "remoto" com "positivo". As séries usam tokens próprios."""
    html = report.render_html(_mercado_ctx())
    assert "--serie-reg:#2a78d6" in html and "--serie-rem:#eb6834" in html
    assert ".bar.rem .fill{background:var(--good)}" not in html
    assert "veredito" in html and "linhaFamilia" in html


def test_ressalva_metodologica_sempre_presente():
    md = report.render_markdown(_mercado_ctx())
    assert "mistura duas causas" in md


def test_render_recalcula_o_mapa_a_partir_das_skills_gravadas(tmp_path):
    """Permite iterar na análise sobre dados reais sem recoletar 12 minutos de vagas."""
    import json
    p = tmp_path / "2026-09-13.json"
    p.write_text(json.dumps({
        "run_date": "2026-09-13", "run_date_br": "13/09/2026", "run_time": "08:30",
        "lookback_days": 7, "cidades": ["Itajaí"], "categorias": {},
        "by_category": {}, "by_city": {},
        "jobs": [{"title": "Dev", "company": "X", "url": "u", "source": "gupy", "score": 70,
                  "is_new": True, "seniority": "junior", "category": None, "matched_city": None,
                  "workplace": "remote", "location": "", "date_posted": None, "age_days": None,
                  "description": "python e aws", "reasons": [], "fit": None, "fit_note": "",
                  "tags": [], "skills": ["python", "aws"]} for _ in range(12)],
        "mercado": {},  # gravado por uma versão anterior, sem o corte por família
    }, ensure_ascii=False), encoding="utf-8")
    ctx = report.load_context(p)
    assert ctx["mercado"]["linhas"], "o mapa tem de ser recalculado, não lido do arquivo"
    assert ctx["mercado"]["grupos"]


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
