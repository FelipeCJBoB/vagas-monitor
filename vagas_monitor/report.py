"""Relatórios: Markdown (reports/), JSON (dados da rodada) e HTML (painel em docs/)."""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, BaseLoader

from .config import ROOT, env
from .models import Job

LEVEL_PT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "unknown": "—"}
WP_PT = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "unknown": ""}
SOURCE_PT = {"linkedin": "LinkedIn", "indeed": "Indeed", "gupy": "Gupy"}


def _age(date_posted: str | None, today: date) -> int | None:
    if not date_posted:
        return None
    try:
        return (today - date.fromisoformat(date_posted[:10])).days
    except ValueError:
        return None


def build_context(jobs: list[Job], cfg: dict, run_dt: datetime, lookback_days: int,
                  source_counts: dict, errors: dict, state_stats: dict) -> dict:
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
        "top_n": int(cfg.get("relatorio", {}).get("top_n", 20)),
        "report_url": cfg.get("relatorio", {}).get("url_publica") or env("REPORT_URL") or "",
        "state_stats": state_stats,
    }


# ----------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------
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
        j["company"].replace("|", "/") or "—",
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
        out += ["> ⚠️ Fontes com problema nesta rodada: " +
                "; ".join(f"**{SOURCE_PT.get(k, k)}** — {v}" for k, v in ctx["errors"].items()), ""]

    hdr = "| Score | Vaga | Empresa | Local | Nível | Categoria | Fonte | Publicada |\n|---:|---|---|---|---|---|---|---|"
    out += [f"## Destaques — top {min(ctx['top_n'], len(new_jobs))} novas", ""]
    if new_jobs:
        out += [hdr] + [_md_row(j, cats) for j in new_jobs[: ctx["top_n"]]] + [""]
    else:
        out += ["_Nenhuma vaga nova nesta rodada._", ""]

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

    out += ["---", "",
            "Score = regras explícitas (categoria no título +30, júnior +25, cidade-alvo +20, remoto +12, "
            "skills do currículo até +18, sênior −30). ★ = avaliação do Claude (0–10). 🆕 = não apareceu em rodadas anteriores.",
            ""]
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
        <option value="fit">Avaliação da IA</option>
      </select>
    </fieldset>
    <label class="toggle"><input type="checkbox" id="onlyNew"> Só vagas novas desta rodada</label>
  </aside>

  <section aria-label="Vagas">
    {% if errors %}<div class="errors">Fontes com problema nesta rodada: {% for k, v in errors.items() %}<b>{{ source_pt.get(k, k) }}</b> — {{ v }}{% if not loop.last %}; {% endif %}{% endfor %}</div>{% endif %}
    <div class="count"><span><b id="n">0</b> vagas</span><span id="hint"></span></div>
    <ol class="jobs" id="list"></ol>
    <p class="foot">Pontuação por regras explícitas: categoria no título +30 · júnior/estágio +25 · cidade-alvo +20 · remoto +12 · skills do currículo até +18 · sênior/liderança −30. ★ = avaliação do Claude (0–10) sobre a descrição completa.</p>
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
      <div class="company">${esc(j.company||"—")}</div>
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
    return json.loads(Path(json_path).read_text(encoding="utf-8"))
