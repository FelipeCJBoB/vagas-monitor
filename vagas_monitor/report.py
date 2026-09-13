"""Relatórios: Markdown (reports/), JSON (dados da rodada) e HTML (painel em docs/)."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, BaseLoader

from . import skills
from .config import ROOT, env
from .models import Job

LEVEL_PT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "unknown": "—"}
WP_PT = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "unknown": ""}
SOURCE_PT = {"linkedin": "LinkedIn", "indeed": "Indeed", "gupy": "Gupy", "claude": "Avaliação por IA", "ia": "Avaliação por IA"}


def _age(date_posted: str | None, today: date) -> int | None:
    if not date_posted:
        return None
    try:
        return (today - date.fromisoformat(date_posted[:10])).days
    except ValueError:
        return None


def build_context(jobs: list[Job], cfg: dict, run_dt: datetime, lookback_days: int,
                  source_counts: dict, errors: dict, state_stats: dict,
                  taxonomia: dict | None = None) -> dict:
    today = run_dt.date()
    jl = []
    for j in jobs:
        d = j.to_dict()
        d["age_days"] = _age(j.date_posted, today)
        jl.append(d)
    cats = {k: {"nome": v["nome"], "prioridade": v.get("prioridade", 9)} for k, v in cfg["categorias"].items()}
    by_cat = {k: sum(1 for j in jl if j["category"] == k) for k in cats}
    by_city = {c: sum(1 for j in jl if j["matched_city"] == c) for c in cfg["cidades"]}
    by_city["Remoto"] = sum(1 for j in jl if not j["matched_city"] and j["workplace"] == "remote")
    return {
        "run_date": today.isoformat(),
        "run_date_br": today.strftime("%d/%m/%Y"),
        "run_time": run_dt.strftime("%H:%M"),
        "lookback_days": lookback_days,
        "jobs": jl,
        "total": len(jl),
        "new_count": sum(1 for j in jl if j["is_new"]),
        "categorias": cats,
        "cidades": list(cfg["cidades"]),
        "by_category": by_cat,
        "by_city": by_city,
        "source_counts": source_counts,
        "errors": errors,
        # quantas vagas realmente receberam nota da IA: a legenda da estrela só
        # aparece quando há estrela, e diz de quantas vagas ela fala
        "ai_count": sum(1 for j in jl if j.get("fit") is not None),
        # mapa "o mercado presencial x o remoto cobram o quê"
        "mercado": skills.analyze(jl, taxonomia or {}),
        "top_n": int(cfg.get("relatorio", {}).get("top_n", 20)),
        "report_url": cfg.get("relatorio", {}).get("url_publica") or env("REPORT_URL") or "",
        "state_stats": state_stats,
    }


# ----------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------
def _company(j: dict) -> str:
    """Nome da empresa para exibição, explicitando quando a fonte não informou.

    O Indeed às vezes publica sem o campo. Quando o link de candidatura aponta para
    o ATS da empresa, o nome é inferido do subdomínio e marcado como tal; quando nem
    isso existe, o card diz que não há empresa em vez de mostrar um traço mudo.
    """
    nome = (j.get("company") or "").strip()
    if not nome:
        return "Empresa não informada"
    return nome + (" (inferida)" if "empresa-inferida" in (j.get("tags") or []) else "")


def _md_place(j: dict) -> str:
    if j["matched_city"]:
        wp = WP_PT.get(j["workplace"], "")
        return j["matched_city"] + (f" ({wp.lower()})" if wp else "")
    if j["workplace"] == "remote":
        return "Remoto"
    return j["location"] or "—"


def _md_date(j: dict) -> str:
    if not j["date_posted"]:
        return "—"
    try:
        d = date.fromisoformat(j["date_posted"][:10]).strftime("%d/%m")
    except ValueError:
        return j["date_posted"]
    a = j["age_days"]
    return d if a is None else (f"{d} (hoje)" if a == 0 else f"{d} ({a}d)")


def _md_row(j: dict, cats: dict, with_cat: bool = True) -> str:
    title = j["title"].replace("|", "/").strip()
    fit = f" ★{j['fit']}/10" if j.get("fit") is not None else ""
    cells = [
        f"**{j['score']}**{fit}",
        f"[{title}]({j['url']})" + (" 🆕" if j["is_new"] else ""),
        _company(j).replace("|", "/"),
        _md_place(j),
        LEVEL_PT.get(j["seniority"], "—"),
    ]
    if with_cat:
        cells.append(cats.get(j["category"], {}).get("nome", "—"))
    cells += [SOURCE_PT.get(j["source"], j["source"]), _md_date(j)]
    row = "| " + " | ".join(cells) + " |"
    if j.get("fit_note"):
        row += f"\n| | ↳ _{j['fit_note'].replace('|', '/')}_ | | | | | | |" if with_cat else \
               f"\n| | ↳ _{j['fit_note'].replace('|', '/')}_ | | | | | |"
    return row


TENHO_PT = {"sim": "já domina", "parcial": "usou em projeto", "nao": "lacuna"}
ONDE_PT = {"presencial": "pesa no presencial", "remoto": "pesa no remoto",
           "ambos": "cobrado nos dois", "indeterminado": "amostra insuficiente"}


def _leitura_do_mercado(m: dict) -> list[str]:
    """Converte os números do mapa em leitura acionável.

    Tudo aqui é derivado da amostra da própria rodada. Se a amostra for pequena,
    o texto diz isso em vez de afirmar tendência.
    """
    linhas, am = m.get("linhas") or [], m.get("amostra") or {}
    if not linhas:
        return []
    reg, rem = am.get("regional", 0), am.get("remoto", 0)
    out = []

    if not am.get("comparavel", True):
        menor = "regional" if reg <= rem else "remoto"
        out.append(f"⚠️ **Comparação entre os dois mercados suspensa nesta rodada.** O lado "
                   f"{menor} tem só {min(reg, rem)} vagas com descrição, abaixo do mínimo de "
                   f"{am.get('min_segmento', 10)}. Com essa amostra, uma única menção viraria "
                   f"vários pontos percentuais. Os números absolutos continuam válidos; a coluna "
                   f"'onde pesa' foi neutralizada.")

    grupos = m.get("grupos") or []
    comparavel = am.get("comparavel", True)

    # a família em que ele já é forte e que domina o mercado local
    casa = next((g for g in grupos if g["dominado"] or not g["faltam"]), None)
    if casa is None:
        casa = max(grupos, key=lambda g: g["pct_regional"] - g["pct_remoto"], default=None)
    if casa and comparavel and casa["pct_regional"] > casa["pct_remoto"]:
        out.append(f"**Seu terreno já conquistado: {casa['grupo']}.** Aparece em "
                   f"{casa['pct_regional']:.0f}% das vagas presenciais da região, contra "
                   f"{casa['pct_remoto']:.0f}% das remotas. É o que você usa todo dia hoje. "
                   "Não é para estudar, é para ocupar o topo do currículo e virar história "
                   "de entrevista com número junto.")

    # a família que mais separa os dois mercados e onde há lacuna
    com_lacuna = [g for g in grupos if g["faltam"]]
    if com_lacuna and comparavel:
        pedagio = max(com_lacuna, key=lambda g: g["pct_remoto"] - g["pct_regional"])
        if pedagio["pct_remoto"] > pedagio["pct_regional"] * 1.5:
            out.append(f"**O pedágio do mercado remoto: {pedagio['grupo']}.** "
                       f"{pedagio['pct_remoto']:.0f}% das vagas remotas pedem, contra "
                       f"{pedagio['pct_regional']:.0f}% das regionais. É a maior distância entre "
                       "os dois mercados nesta rodada, e é onde suas lacunas se concentram: "
                       + ", ".join(pedagio["faltam"][:4]) + ".")

    forca = [r for r in linhas if r["tenho"] == "sim"][:5]
    if forca:
        out.append("**O que já joga a seu favor, item a item.** " + ", ".join(
            f"{r['nome']} ({r['pct_acessivel']:.0f}%)" for r in forca) +
            ". Percentual é a fatia das vagas acessíveis em que cada um aparece.")

    faltam = skills.prioridades(m, limite=3)
    if faltam:
        out.append("**Onde o estudo rende mais.** " + "; ".join(
            f"{r['nome']} destrava {r['pct_acessivel']:.0f}% das vagas acessíveis e hoje é "
            f"{TENHO_PT[r['tenho']]}" for r in faltam) + ".")

    out.append("**Como ler a diferença entre os dois mercados.** Ela mistura duas causas. As vagas "
               "remotas vêm de empresas de tecnologia e tendem a ser mais sêniores; as regionais "
               "incluem cargos de ERP e suporte que pedem menos stack. Parte do contraste é o tipo "
               "de empresa, não o regime de trabalho. Vale como direção, não como medida exata.")
    return out


def _secao_mercado(ctx: dict) -> list[str]:
    m = ctx.get("mercado") or {}
    linhas = m.get("linhas") or []
    if not linhas:
        return []
    am = m["amostra"]
    out = [
        "## O que o mercado cobra",
        "",
        f"Base desta rodada: **{am['regional']} vagas presenciais ou híbridas na região** "
        f"(de {am['regional_total']}) e **{am['remoto']} remotas** (de {am['remoto_total']}) "
        f"com descrição legível, cobertura de {am['cobertura_pct']:.0f}%. "
        f"Percentuais calculados só sobre vagas com descrição; habilidade com menos de "
        f"{m['min_ocorrencias']} ocorrências fica de fora por ser ruído.",
        "",
    ]
    out += [f"- {t}" for t in _leitura_do_mercado(m)] + [""]

    grupos = m.get("grupos") or []
    if grupos:
        out += ["### Por família de tecnologia", "",
                "Uma vaga conta uma vez por família, mesmo citando três tecnologias dela. Este corte "
                "existe porque AWS, Azure e Google Cloud competem entre si na tabela item a item e "
                "cada uma parece modesta, quando na verdade são a mesma lacuna.", "",
                "| Família | Presencial região | Remoto nacional | Vagas acessíveis | O que falta em você |",
                "|---|---:|---:|---:|---|"]
        for g in grupos:
            falta = "— domina" if g["dominado"] else ", ".join(g["faltam"][:4])
            out.append(f"| **{g['grupo']}** | {g['pct_regional']:.0f}% | {g['pct_remoto']:.0f}% | "
                       f"{g['pct_acessivel']:.0f}% | {falta} |")
        out.append("")

    faltam = skills.prioridades(m, limite=8)
    if faltam:
        out += ["### Prioridade de estudo", "",
                "Ordem por quanto cada item destrava candidaturas que você pode realmente pegar "
                "(júnior, pleno ou sem nível declarado), descontando o que já domina.", "",
                "| # | Habilidade | Aparece em | Onde pesa | Situação |",
                "|---:|---|---:|---|---|"]
        for i, r in enumerate(faltam, 1):
            out.append(f"| {i} | **{r['nome']}** | {r['pct_acessivel']:.0f}% das acessíveis | "
                       f"{ONDE_PT[r['onde']]} | {TENHO_PT[r['tenho']]} |")
        out.append("")

    out += ["### Mapa completo", "",
            "| Habilidade | Grupo | Presencial região | Remoto nacional | Onde pesa | Você |",
            "|---|---|---:|---:|---|---|"]
    for r in linhas:
        out.append(f"| {r['nome']} | {r['grupo']} | {r['pct_regional']:.0f}% ({r['n_regional']}) | "
                   f"{r['pct_remoto']:.0f}% ({r['n_remoto']}) | {ONDE_PT[r['onde']]} | "
                   f"{TENHO_PT[r['tenho']]} |")
    out += ["", "Marcação de domínio vem de `skills.yaml`, campo `tenho`. Ajuste lá conforme "
                "for estudando e a prioridade se recalcula sozinha na próxima rodada.", ""]
    return out


def render_markdown(ctx: dict) -> str:
    cats = ctx["categorias"]
    jobs = ctx["jobs"]
    new_jobs = [j for j in jobs if j["is_new"]]
    src = " · ".join(f"{SOURCE_PT.get(k, k)} {v}" for k, v in ctx["source_counts"].items())
    out = [
        f"# Radar de Vagas — {ctx['run_date_br']}",
        "",
        f"**{ctx['new_count']} vagas novas** · {ctx['total']} na janela de {ctx['lookback_days']} dias · "
        f"gerado {ctx['run_date_br']} {ctx['run_time']}  ",
        f"Fontes (brutas): {src or '—'}  ",
        "Cidades: " + ", ".join(ctx["cidades"]) + " · Remoto (Brasil) incluído  ",
        "Por categoria: " + " · ".join(f"{cats[k]['nome']} {v}" for k, v in ctx["by_category"].items()) + "  ",
        "Por local: " + " · ".join(f"{k} {v}" for k, v in ctx["by_city"].items() if v),
        "",
    ]
    if ctx["errors"]:
        out += ["> ⚠️ Problemas nesta rodada: " +
                "; ".join(f"**{SOURCE_PT.get(k, k)}** — {v}" for k, v in ctx["errors"].items()), ""]

    hdr = "| Score | Vaga | Empresa | Local | Nível | Categoria | Fonte | Publicada |\n|---:|---|---|---|---|---|---|---|"
    out += [f"## Destaques — top {min(ctx['top_n'], len(new_jobs))} novas", ""]
    if new_jobs:
        out += [hdr] + [_md_row(j, cats) for j in new_jobs[: ctx["top_n"]]] + [""]
    else:
        out += ["_Nenhuma vaga nova nesta rodada._", ""]

    out += _secao_mercado(ctx)

    hdr2 = "| Score | Vaga | Empresa | Local | Nível | Fonte | Publicada |\n|---:|---|---|---|---|---|---|"
    for key in sorted(cats, key=lambda k: cats[k]["prioridade"]):
        group = [j for j in jobs if j["category"] == key]
        if not group:
            continue
        out += [f"## {cats[key]['nome']} ({len(group)})", ""]
        local = [j for j in group if j["matched_city"]]
        remote = [j for j in group if not j["matched_city"]]
        if local:
            out += [f"### Na região ({len(local)})", "", hdr2] + [_md_row(j, cats, False) for j in local] + [""]
        if remote:
            out += [f"### Remoto ({len(remote)})", "", hdr2] + [_md_row(j, cats, False) for j in remote] + [""]

    legenda = ("Score = regras explícitas (categoria no título +30, júnior +25, cidade-alvo +20, remoto +12, "
               "skills do currículo até +18, sênior −30).")
    if ctx["ai_count"]:
        legenda += (f" ★ = avaliação do Claude (0–10), aplicada às {ctx['ai_count']} melhores vagas novas "
                    f"de um total de {ctx['new_count']}.")
    legenda += " 🆕 = não apareceu em rodadas anteriores."
    out += ["---", "", legenda, ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------
# HTML (painel) — mesmo arquivo serve como Artifact e como página do GitHub Pages
# ----------------------------------------------------------------------------
HTML_TEMPLATE = r"""<title>Radar de Vagas SC</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:wght@500;600&display=swap">
<style>
:root{
  --bg:#F3F6F5;--surface:#FFFFFF;--ink:#16212A;--muted:#5D6B76;--line:#D6DFE1;
  --accent:#0E6B70;--accent-ink:#FFFFFF;--accent-soft:#D9ECEC;--chip:#EAF0EF;
  --good:#2C7A4B;--good-soft:#DCEFE3;--warn:#B8741F;--warn-soft:#F6E9D2;--low:#8794A0;
  --shadow:0 1px 2px rgba(22,33,42,.06);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0E1316;--surface:#151B20;--ink:#E3E8EB;--muted:#93A0A9;--line:#26313A;
    --accent:#4FB7BB;--accent-ink:#0B1214;--accent-soft:#143A3C;--chip:#1D262C;
    --good:#5DC087;--good-soft:#173627;--warn:#DBA050;--warn-soft:#3A2B12;--low:#6C7983;--shadow:none;
  }
}
:root[data-theme="dark"]{
  --bg:#0E1316;--surface:#151B20;--ink:#E3E8EB;--muted:#93A0A9;--line:#26313A;
  --accent:#4FB7BB;--accent-ink:#0B1214;--accent-soft:#143A3C;--chip:#1D262C;
  --good:#5DC087;--good-soft:#173627;--warn:#DBA050;--warn-soft:#3A2B12;--low:#6C7983;--shadow:none;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Source Sans 3","Segoe UI",system-ui,sans-serif;font-size:15.5px;line-height:1.45}
a{color:inherit}
.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;padding:26px 28px 18px;border-bottom:1px solid var(--line);background:var(--surface)}
h1{font-family:Sora,"Segoe UI",sans-serif;font-weight:700;font-size:26px;letter-spacing:-.01em;margin:0;text-wrap:balance}
.sub{margin:4px 0 0;color:var(--muted);max-width:70ch}
.run{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:12.5px;color:var(--muted);text-align:right;line-height:1.6}
.run b{color:var(--ink);font-weight:600}
.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:26px;padding:22px 28px 64px;max-width:1240px;margin:0 auto}
.filters{position:sticky;top:16px;align-self:start;display:flex;flex-direction:column;gap:18px}
.filters fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:8px;min-width:0}
.filters legend,.lbl{display:block;font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600;padding:0;margin-bottom:6px}
.search,select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);font:inherit}
.search:focus,select:focus,button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chipbtn{border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:5px 10px;border-radius:999px;font:inherit;font-size:13.5px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.chipbtn .n{font-family:"JetBrains Mono",monospace;font-size:11.5px;color:var(--muted)}
.chipbtn[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.chipbtn[aria-pressed="true"] .n{color:inherit;opacity:.85}
.toggle{display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer}
.count{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 10px;color:var(--muted);font-size:14px}
.count b{color:var(--ink);font-family:Sora,sans-serif;font-size:18px;font-weight:600}
ol.jobs{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.job{display:grid;grid-template-columns:60px minmax(0,1fr);gap:14px;background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--low);border-radius:8px;padding:12px 14px 12px 12px;box-shadow:var(--shadow)}
.job.band-high{border-left-color:var(--good)}.job.band-mid{border-left-color:var(--accent)}
.score{display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.score .num{font-size:24px;font-weight:600;line-height:1}
.score .lbl{font-size:10px;margin:4px 0 0;color:var(--muted)}
.band-high .num{color:var(--good)}.band-mid .num{color:var(--accent)}.band-low .num{color:var(--low)}
.head{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline}
.title{font-family:Sora,"Segoe UI",sans-serif;font-weight:600;font-size:16px;text-decoration:none;text-wrap:balance}
.title:hover{text-decoration:underline;text-decoration-color:var(--accent)}
.new{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.company{color:var(--muted);margin-top:2px}
.meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;align-items:center;font-size:13px}
.pill{padding:2px 8px;border-radius:999px;background:var(--chip);color:var(--ink);white-space:nowrap}
.pill.city{background:var(--accent-soft);color:var(--accent)}
.pill.jr{background:var(--good-soft);color:var(--good)}.pill.sr{background:var(--warn-soft);color:var(--warn)}
.src,.age{color:var(--muted)}
.fit{margin:8px 0 0;padding:8px 10px;border-radius:6px;background:var(--chip);font-size:14px;max-width:80ch}
.fit b{font-family:"JetBrains Mono",monospace;color:var(--accent)}
details{margin-top:6px;font-size:13.5px;color:var(--muted)}summary{cursor:pointer}
details ul{margin:6px 0 0 18px;padding:0}details p{margin:6px 0 0;max-width:70ch}
.empty{padding:40px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:8px}
.tabs{display:flex;gap:4px;margin:0 0 14px;border-bottom:1px solid var(--line)}
.tab{border:0;border-bottom:2px solid transparent;background:none;color:var(--muted);font:inherit;font-weight:600;padding:8px 14px;cursor:pointer;margin-bottom:-1px}
.tab[aria-selected="true"]{color:var(--accent);border-bottom-color:var(--accent)}
.nota{margin:0 0 10px;padding:10px 12px;border-left:3px solid var(--accent);background:var(--chip);border-radius:0 6px 6px 0;font-size:14px;max-width:80ch}
.nota.alerta{border-left-color:var(--warn);background:var(--warn-soft);color:var(--warn)}
.nota b{color:var(--ink)}.nota.alerta b{color:inherit}
.mgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:6px;margin:0 0 22px}
.srow{display:grid;grid-template-columns:26px minmax(120px,1.4fr) minmax(90px,2fr) 108px;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:9px 12px}
.srow .pos{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.srow .nm{font-weight:600;min-width:0}
.srow .gp{display:block;font-weight:400;font-size:12px;color:var(--muted)}
.bars{display:flex;flex-direction:column;gap:3px;min-width:0}
.bar{display:grid;grid-template-columns:52px minmax(0,1fr) 40px;gap:7px;align-items:center;font-size:11.5px;color:var(--muted)}
.bar .track{height:7px;border-radius:4px;background:var(--chip);overflow:hidden}
.bar .fill{display:block;height:100%;border-radius:4px;background:var(--accent)}
.bar.rem .fill{background:var(--good)}
.bar .val{font-family:"JetBrains Mono",monospace;text-align:right;font-variant-numeric:tabular-nums}
.tag{justify-self:end;font-size:11.5px;padding:3px 9px;border-radius:999px;background:var(--chip);white-space:nowrap}
.tag.gap{background:var(--warn-soft);color:var(--warn)}
.tag.tem{background:var(--good-soft);color:var(--good)}
@media (max-width:700px){.srow{grid-template-columns:22px minmax(0,1fr);row-gap:8px}.srow .bars,.srow .tag{grid-column:1/-1;justify-self:start}}
.errors{margin:0 0 14px;padding:10px 12px;border-radius:6px;background:var(--warn-soft);color:var(--warn);font-size:13.5px}
.foot{margin:28px 0 0;color:var(--muted);font-size:13px;max-width:80ch}
@media (max-width:820px){
  .layout{grid-template-columns:1fr;padding:16px}.top{padding:20px 16px 14px}.run{text-align:left}
  .filters{position:static}
}
</style>

<header class="top">
  <div>
    <h1>Radar de Vagas</h1>
    <p class="sub">{{ cidades|join(' · ') }} · Remoto (Brasil) — Dados, IA/LLMs, Agentes de IA e Full Stack</p>
  </div>
  <div class="run">
    atualizado <b>{{ run_date_br }} {{ run_time }}</b><br>
    <b>{{ new_count }}</b> novas · {{ total }} na janela de {{ lookback_days }} dias<br>
    {% for k, v in source_counts.items() %}{{ source_pt.get(k, k) }} {{ v }}{% if not loop.last %} · {% endif %}{% endfor %}
  </div>
</header>

<main class="layout">
  <aside class="filters" aria-label="Filtros">
    <div>
      <label class="lbl" for="q">Buscar</label>
      <input id="q" class="search" type="search" placeholder="título, empresa, skill…" autocomplete="off">
    </div>
    <fieldset><legend>Categoria</legend><div class="chips" id="cats"></div></fieldset>
    <fieldset><legend>Local</legend><select id="place" aria-label="Local"></select></fieldset>
    <fieldset><legend>Nível</legend><div class="chips" id="levels"></div></fieldset>
    <fieldset><legend>Ordenar</legend>
      <select id="sort" aria-label="Ordenar">
        <option value="score">Maior pontuação</option>
        <option value="date">Mais recentes</option>
        {% if ai_count %}<option value="fit">Avaliação da IA</option>{% endif %}
      </select>
    </fieldset>
    <label class="toggle"><input type="checkbox" id="onlyNew"> Só vagas novas desta rodada</label>
  </aside>

  <section aria-label="Vagas">
    {% if errors %}<div class="errors">Problemas nesta rodada: {% for k, v in errors.items() %}<b>{{ source_pt.get(k, k) }}</b> — {{ v }}{% if not loop.last %}; {% endif %}{% endfor %}</div>{% endif %}
    {% if mercado.get('linhas') %}
    <div class="tabs" role="tablist">
      <button class="tab" id="tabVagas" role="tab" aria-selected="true">Vagas</button>
      <button class="tab" id="tabMercado" role="tab" aria-selected="false">O que estudar</button>
    </div>
    {% endif %}
    <div class="count"><span><b id="n">0</b> vagas</span><span id="hint"></span></div>
    <ol class="jobs" id="list"></ol>
    <div id="mercado" hidden></div>
    <p class="foot">Pontuação por regras explícitas: categoria no título +30 · júnior/estágio +25 · cidade-alvo +20 · remoto +12 · skills do currículo até +18 · sênior/liderança −30.{% if ai_count %} ★ = avaliação do Claude (0–10) sobre a descrição completa, aplicada às {{ ai_count }} melhores vagas novas de um total de {{ new_count }}.{% endif %}</p>
  </section>
</main>

<script>
const DATA = {{ data_json|safe }};
const LEVEL = {junior:"Júnior", pleno:"Pleno", senior:"Sênior", unknown:"Nível n/i"};
const WP = {remote:"Remoto", hybrid:"Híbrido", onsite:"Presencial", unknown:""};
const SRC = {linkedin:"LinkedIn", indeed:"Indeed", gupy:"Gupy"};
const cats = Object.entries(DATA.categorias).sort((a,b)=>a[1].prioridade-b[1].prioridade);
const st = {q:"", cats:new Set(), levels:new Set(), place:"all", sort:"score", onlyNew: DATA.new_count>0 && DATA.new_count<DATA.total};
const $ = s => document.querySelector(s);
const esc = s => String(s??"").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const norm = s => String(s??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
const age = d => d==null ? "data n/i" : d===0 ? "hoje" : d===1 ? "ontem" : `há ${d} dias`;
const place = j => j.matched_city ? j.matched_city : (j.workplace==="remote" ? "Remoto" : (j.location||"local n/i"));
// o Indeed às vezes publica sem o campo empresa; dizer isso é melhor que um traço mudo
const company = j => (j.company||"").trim() || "Empresa não informada";

function chip(container, key, label, count, set){
  const b = document.createElement("button");
  b.type="button"; b.className="chipbtn"; b.setAttribute("aria-pressed", set.has(key) ? "true":"false");
  b.innerHTML = `${esc(label)} <span class="n">${count}</span>`;
  b.onclick = () => { set.has(key) ? set.delete(key) : set.add(key); b.setAttribute("aria-pressed", set.has(key)?"true":"false"); render(); };
  container.appendChild(b);
}
function buildFilters(){
  const cc = $("#cats"); cc.innerHTML="";
  for (const [k,v] of cats) chip(cc, k, v.nome, DATA.jobs.filter(j=>j.category===k).length, st.cats);
  const lc = $("#levels"); lc.innerHTML="";
  for (const k of ["junior","pleno","unknown","senior"]) chip(lc, k, LEVEL[k], DATA.jobs.filter(j=>j.seniority===k).length, st.levels);
  const ps = $("#place"); ps.innerHTML="";
  const opt = (v,l) => { const o=document.createElement("option"); o.value=v; o.textContent=l; ps.appendChild(o); };
  opt("all", `Todos (${DATA.total})`);
  opt("region", `Na região (${DATA.jobs.filter(j=>j.matched_city).length})`);
  for (const c of DATA.cidades){ const n=DATA.jobs.filter(j=>j.matched_city===c).length; if(n) opt(c, `${c} (${n})`); }
  opt("remote", `Remoto (${DATA.jobs.filter(j=>!j.matched_city && j.workplace==="remote").length})`);
  $("#onlyNew").checked = st.onlyNew;
}
function filtered(){
  const q = norm(st.q).trim();
  let out = DATA.jobs.filter(j => {
    if (st.onlyNew && !j.is_new) return false;
    if (st.cats.size && !st.cats.has(j.category)) return false;
    if (st.levels.size && !st.levels.has(j.seniority)) return false;
    if (st.place==="region" && !j.matched_city) return false;
    if (st.place==="remote" && (j.matched_city || j.workplace!=="remote")) return false;
    if (!["all","region","remote"].includes(st.place) && j.matched_city!==st.place) return false;
    if (q && !norm([j.title,j.company,j.location,j.description,j.fit_note].join(" ")).includes(q)) return false;
    return true;
  });
  if (st.sort==="date") out.sort((a,b)=>(b.date_posted||"").localeCompare(a.date_posted||"") || b.score-a.score);
  else if (st.sort==="fit") out.sort((a,b)=>((b.fit??-1)-(a.fit??-1)) || b.score-a.score);
  else out.sort((a,b)=>b.score-a.score || (b.date_posted||"").localeCompare(a.date_posted||""));
  return out;
}
function row(j){
  const band = j.score>=70 ? "band-high" : j.score>=45 ? "band-mid" : "band-low";
  const sen = j.seniority==="junior" ? "pill jr" : j.seniority==="senior" ? "pill sr" : "pill";
  const wp = WP[j.workplace] || "";
  const catName = (DATA.categorias[j.category]||{}).nome || "";
  const fit = j.fit!=null ? `<p class="fit"><b>★ ${j.fit}/10</b> ${esc(j.fit_note)}</p>` : "";
  const reasons = (j.reasons||[]).map(r=>`<li>${esc(r)}</li>`).join("");
  const desc = j.description ? `<p>${esc(j.description.slice(0,600))}${j.description.length>600?"…":""}</p>` : "";
  return `<li class="job ${band}">
    <div class="score"><span class="num">${j.score}</span><span class="lbl">match</span></div>
    <div>
      <div class="head"><a class="title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${j.is_new?'<span class="new">nova</span>':''}</div>
      <div class="company">${esc(company(j))}${j.tags && j.tags.includes("empresa-inferida") ? ' <span class="pill">inferida do site da vaga</span>' : ""}</div>
      <div class="meta">
        <span class="pill ${j.matched_city?'city':''}">${esc(place(j))}</span>
        ${wp && j.matched_city ? `<span class="pill">${wp}</span>`:""}
        <span class="${sen}">${LEVEL[j.seniority]||"—"}</span>
        ${catName?`<span class="pill">${esc(catName)}</span>`:""}
        <span class="src">${SRC[j.source]||j.source}</span>
        <span class="age">${age(j.age_days)}</span>
      </div>
      ${fit}
      <details><summary>Por que ${j.score} pontos</summary><ul>${reasons||"<li>—</li>"}</ul>${desc}</details>
    </div>
  </li>`;
}
function render(){
  const out = filtered();
  $("#n").textContent = out.length;
  $("#hint").textContent = st.onlyNew ? `de ${DATA.new_count} novas` : `de ${DATA.total} na janela`;
  $("#list").innerHTML = out.length ? out.map(row).join("") : `<li class="empty">Nenhuma vaga com esses filtros.</li>`;
}
// --- aba "O que estudar" ---------------------------------------------------
const TENHO = {sim:["já domina","tem"], parcial:["usou em projeto","tem"], nao:["lacuna","gap"]};
const ONDE = {presencial:"pesa no presencial", remoto:"pesa no remoto",
              ambos:"cobrado nos dois", indeterminado:"amostra insuficiente"};
function barra(rotulo, pct, n, classe){
  return `<div class="bar ${classe}"><span>${rotulo}</span>
    <span class="track"><i class="fill" style="width:${Math.min(100,pct)}%"></i></span>
    <span class="val">${pct.toFixed(0)}%</span></div>`;
}
function linhaSkill(r, i){
  const [rotulo, cls] = TENHO[r.tenho] || TENHO.nao;
  return `<li class="srow">
    <span class="pos">${i}</span>
    <span class="nm">${esc(r.nome)}<span class="gp">${esc(r.grupo)} · ${ONDE[r.onde]||""}</span></span>
    <span class="bars">${barra("região", r.pct_regional, r.n_regional, "reg")}${barra("remoto", r.pct_remoto, r.n_remoto, "rem")}</span>
    <span class="tag ${cls}">${rotulo}</span>
  </li>`;
}
function renderMercado(){
  const m = DATA.mercado || {}, linhas = m.linhas || [];
  if (!linhas.length) return;
  const am = m.amostra || {};
  const faltam = linhas.filter(r => r.prioridade > 0).slice(0, 8);
  const notas = (DATA.leitura || []).map(t => {
    const alerta = t.startsWith("⚠️");
    // o texto vem em markdown leve: **negrito** vira <b>
    const html = esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    return `<p class="nota${alerta ? " alerta" : ""}">${html}</p>`;
  }).join("");
  $("#mercado").innerHTML = `
    ${notas}
    <p class="foot" style="margin:0 0 16px">Base: <b>${am.regional}</b> vagas presenciais ou híbridas na região
      (de ${am.regional_total}) e <b>${am.remoto}</b> remotas (de ${am.remoto_total}) com descrição legível.
      Percentuais só sobre vagas com descrição; abaixo de ${m.min_ocorrencias} menções a habilidade fica de fora.</p>
    ${(m.grupos||[]).length ? `<h3 style="font-family:Sora,sans-serif;font-size:15px;margin:0 0 8px">Por família de tecnologia</h3>
    <p class="foot" style="margin:0 0 10px">Uma vaga conta uma vez por família. AWS, Azure e Google Cloud
      competem entre si na lista item a item e cada uma parece modesta, quando são a mesma lacuna.</p>
    <ol class="mgrid">${m.grupos.map((g,i)=>`<li class="srow">
      <span class="pos">${i+1}</span>
      <span class="nm">${esc(g.grupo)}<span class="gp">${g.dominado ? "você domina" : "falta: " + esc(g.faltam.slice(0,3).join(", "))}</span></span>
      <span class="bars">${barra("região", g.pct_regional, 0, "reg")}${barra("remoto", g.pct_remoto, 0, "rem")}</span>
      <span class="tag ${g.dominado ? "tem" : "gap"}">${g.pct_acessivel.toFixed(0)}% acessíveis</span>
    </li>`).join("")}</ol>` : ""}
    ${faltam.length ? `<h3 style="font-family:Sora,sans-serif;font-size:15px;margin:0 0 8px">Prioridade de estudo</h3>
    <p class="foot" style="margin:0 0 10px">Ordem por quanto cada item destrava vagas que você pode pegar hoje
      (júnior, pleno ou sem nível declarado), descontando o que já domina.</p>
    <ol class="mgrid">${faltam.map((r,i)=>linhaSkill(r,i+1)).join("")}</ol>` : ""}
    <h3 style="font-family:Sora,sans-serif;font-size:15px;margin:0 0 8px">Mapa completo</h3>
    <ol class="mgrid">${linhas.map((r,i)=>linhaSkill(r,i+1)).join("")}</ol>
    <p class="foot">A marcação "já domina / usou em projeto / lacuna" vem do arquivo <code>skills.yaml</code>.
      Atualize conforme for estudando e a prioridade se recalcula na próxima rodada.</p>`;
}
function aba(mercado){
  const tv = $("#tabVagas"), tm = $("#tabMercado");
  if (!tv) return;
  tv.setAttribute("aria-selected", String(!mercado));
  tm.setAttribute("aria-selected", String(mercado));
  $("#list").hidden = mercado;
  $("#mercado").hidden = !mercado;
  document.querySelector(".count").hidden = mercado;
  document.querySelector(".filters").style.visibility = mercado ? "hidden" : "";
}
if ($("#tabVagas")){
  $("#tabVagas").addEventListener("click", () => aba(false));
  $("#tabMercado").addEventListener("click", () => aba(true));
  renderMercado();
}

$("#q").addEventListener("input", e => { st.q = e.target.value; render(); });
$("#place").addEventListener("change", e => { st.place = e.target.value; render(); });
$("#sort").addEventListener("change", e => { st.sort = e.target.value; render(); });
$("#onlyNew").addEventListener("change", e => { st.onlyNew = e.target.checked; render(); });
buildFilters(); render();
</script>
"""


def render_html(ctx: dict) -> str:
    env_ = Environment(loader=BaseLoader(), autoescape=True)
    tpl = env_.from_string(HTML_TEMPLATE)
    data = {k: ctx[k] for k in ("jobs", "total", "new_count", "categorias", "cidades", "run_date_br")}
    data["mercado"] = ctx.get("mercado") or {}
    data["leitura"] = _leitura_do_mercado(data["mercado"]) if data["mercado"].get("linhas") else []
    data_json = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028")
    return tpl.render(**ctx, source_pt=SOURCE_PT, data_json=data_json)


# ----------------------------------------------------------------------------
def write_all(ctx: dict, cfg: dict) -> dict:
    rel = cfg.get("relatorio", {})
    folder = ROOT / rel.get("pasta", "reports")
    folder.mkdir(parents=True, exist_ok=True)
    md_path = folder / f"{ctx['run_date']}.md"
    md_path.write_text(render_markdown(ctx), encoding="utf-8")
    shutil.copyfile(md_path, folder / "LATEST.md")
    json_path = folder / f"{ctx['run_date']}.json"
    json_path.write_text(json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")
    html_path = ROOT / rel.get("html", "docs/index.html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(ctx), encoding="utf-8")
    return {"md": md_path, "latest": folder / "LATEST.md", "json": json_path, "html": html_path}


def load_context(json_path: Path) -> dict:
    """Lê o JSON de uma rodada, completando campos que versões anteriores não gravavam.

    O comando `render` existe para refazer o Markdown e o painel de rodadas passadas.
    Sem esse preenchimento, um relatório antigo derruba o render assim que a versão
    nova passa a ler uma chave que não existia quando ele foi gerado.
    """
    ctx = json.loads(Path(json_path).read_text(encoding="utf-8"))
    jobs = ctx.get("jobs") or []
    ctx.setdefault("jobs", jobs)
    ctx.setdefault("ai_count", sum(1 for j in jobs if j.get("fit") is not None))
    ctx.setdefault("total", len(jobs))
    ctx.setdefault("new_count", sum(1 for j in jobs if j.get("is_new")))
    ctx.setdefault("errors", {})
    # o mapa de mercado é recalculado, e não lido do arquivo: as habilidades por vaga
    # já estão gravadas, então `render` reflete a versão atual da análise sem precisar
    # coletar tudo de novo. É o que permite iterar na metodologia sobre dados reais.
    if any(j.get("skills") for j in jobs):
        ctx["mercado"] = skills.analyze(jobs, skills.load_taxonomy(ROOT))
    ctx.setdefault("mercado", {})
    ctx.setdefault("source_counts", {})
    ctx.setdefault("report_url", "")
    ctx.setdefault("top_n", 20)
    ctx.setdefault("state_stats", {})
    return ctx
