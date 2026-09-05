"""Telegram — envia o resumo das vagas novas via Bot API."""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path

import requests

log = logging.getLogger("vagas.telegram")
API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000  # limite do Telegram é 4096

LEVEL_PT = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "unknown": "nível n/i"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _place(j: dict) -> str:
    if j.get("matched_city"):
        wp = {"remote": "remoto", "hybrid": "híbrido", "onsite": "presencial"}.get(j.get("workplace"), "")
        return j["matched_city"] + (f" · {wp}" if wp else "")
    if j.get("workplace") == "remote":
        return "Remoto"
    return j.get("location") or "local n/i"


def build_messages(ctx: dict, top_n: int = 15) -> list[str]:
    """Quebra o resumo em mensagens <= 4000 caracteres."""
    new_jobs = [j for j in ctx["jobs"] if j.get("is_new")]
    cats = ctx["categorias"]
    head = (f"🎯 <b>Radar de Vagas</b> — {ctx['run_date_br']}\n"
            f"{len(new_jobs)} novas · {ctx['total']} na janela de {ctx['lookback_days']} dias\n")
    if not new_jobs:
        head += "\nNenhuma vaga nova nesta rodada."
        if ctx.get("report_url"):
            head += f"\n<a href=\"{esc(ctx['report_url'])}\">Relatório completo</a>"
        return [head]

    lines: list[str] = []
    for i, j in enumerate(new_jobs[:top_n], 1):
        fit = f" · ★{j['fit']}/10" if j.get("fit") is not None else ""
        line = (f"\n<b>{i}. {j['score']}</b>{fit} · <a href=\"{esc(j['url'])}\">{esc(j['title'])}</a>\n"
                f"   {esc(j['company'])} · {esc(_place(j))} · {LEVEL_PT.get(j.get('seniority'), 'n/i')} · "
                f"{esc(cats.get(j.get('category'), {}).get('nome', ''))}")
        if j.get("fit_note"):
            line += f"\n   <i>{esc(j['fit_note'][:220])}</i>"
        lines.append(line)
    rest = len(new_jobs) - min(top_n, len(new_jobs))
    tail = f"\n\n… e mais {rest} no relatório." if rest > 0 else ""
    if ctx.get("report_url"):
        tail += f"\n<a href=\"{esc(ctx['report_url'])}\">Relatório completo</a>"

    msgs, cur = [], head
    for ln in lines:
        if len(cur) + len(ln) > MAX_LEN:
            msgs.append(cur)
            cur = ""
        cur += ln
    cur += tail
    msgs.append(cur)
    return msgs


def send_message(token: str, chat_id: str, text: str) -> bool:
    r = requests.post(API.format(token=token, method="sendMessage"), json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }, timeout=30)
    if not r.ok:
        log.error("telegram %s: %s", r.status_code, r.text[:300])
    return r.ok


def send(token: str, chat_id: str, ctx: dict, top_n: int = 15) -> int:
    ok = 0
    for m in build_messages(ctx, top_n):
        ok += int(send_message(token, chat_id, m))
    return ok


def discover_chat_id(token: str) -> list[tuple[str, str]]:
    """Lista chats que mandaram mensagem ao bot (para achar o chat_id)."""
    r = requests.get(API.format(token=token, method="getUpdates"), timeout=30)
    r.raise_for_status()
    found: dict[str, str] = {}
    for u in r.json().get("result", []):
        msg = u.get("message") or u.get("edited_message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("username", "")
            found[str(chat["id"])] = name
    return list(found.items())


def write_env(path: Path, key: str, value: str) -> None:
    """Grava/atualiza KEY=value no .env sem tocar no resto."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    path.write_text(text, encoding="utf-8")
