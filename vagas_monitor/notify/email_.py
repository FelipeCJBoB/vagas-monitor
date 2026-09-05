"""E-mail — envia o relatório por SMTP (Gmail com senha de app funciona)."""
from __future__ import annotations

import html
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger("vagas.email")
LEVEL_PT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "unknown": "—"}


def build_html(ctx: dict, top_n: int = 40) -> str:
    new_jobs = [j for j in ctx["jobs"] if j.get("is_new")][:top_n]
    cats = ctx["categorias"]
    rows = []
    for j in new_jobs:
        place = j.get("matched_city") or ("Remoto" if j.get("workplace") == "remote" else j.get("location", ""))
        fit = f"★ {j['fit']}/10" if j.get("fit") is not None else ""
        note = f"<div style='color:#5F6C77;font-size:13px'>{html.escape(j.get('fit_note') or '')}</div>" if j.get("fit_note") else ""
        rows.append(
            "<tr>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2;font-weight:700;color:#0E6B70'>{j['score']}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2'><a href='{html.escape(j['url'])}' style='color:#17222B'>{html.escape(j['title'])}</a>"
            f"<div style='color:#5F6C77'>{html.escape(j['company'])}</div>{note}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2'>{html.escape(place)}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2'>{LEVEL_PT.get(j.get('seniority'), '—')}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2'>{html.escape(cats.get(j.get('category'), {}).get('nome', ''))}</td>"
            f"<td style='padding:8px;border-bottom:1px solid #D8E0E2'>{fit}</td>"
            "</tr>"
        )
    table = ("<table style='border-collapse:collapse;width:100%;font-family:Segoe UI,Arial,sans-serif;font-size:14px'>"
             "<tr style='text-align:left;color:#5F6C77'><th style='padding:8px'>Score</th><th style='padding:8px'>Vaga</th>"
             "<th style='padding:8px'>Local</th><th style='padding:8px'>Nível</th><th style='padding:8px'>Categoria</th><th style='padding:8px'>IA</th></tr>"
             + "".join(rows) + "</table>") if rows else "<p>Nenhuma vaga nova nesta rodada.</p>"
    link = f"<p><a href='{html.escape(ctx['report_url'])}'>Relatório completo</a></p>" if ctx.get("report_url") else ""
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;color:#17222B'>"
            f"<h2 style='margin:0 0 4px'>Radar de Vagas — {ctx['run_date_br']}</h2>"
            f"<p style='margin:0 0 16px;color:#5F6C77'>{ctx['new_count']} novas · {ctx['total']} na janela de {ctx['lookback_days']} dias</p>"
            f"{table}{link}</div>")


def send(host: str, port: int, user: str, password: str, to: str, ctx: dict, md_path: Path | None = None) -> bool:
    msg = EmailMessage()
    msg["Subject"] = f"Radar de Vagas — {ctx['run_date_br']} — {ctx['new_count']} novas"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(f"Radar de Vagas {ctx['run_date_br']}: {ctx['new_count']} vagas novas. Abra em um cliente com HTML.")
    msg.add_alternative(build_html(ctx), subtype="html")
    if md_path and Path(md_path).exists():
        msg.add_attachment(Path(md_path).read_bytes(), maintype="text", subtype="markdown", filename=Path(md_path).name)
    try:
        with smtplib.SMTP_SSL(host, int(port), timeout=60) as s:
            s.login(user, password)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("email falhou: %s", e)
        return False
