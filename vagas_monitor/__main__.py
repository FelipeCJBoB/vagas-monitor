"""CLI: python -m vagas_monitor <comando>"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows: acentos no console
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S",
                        stream=sys.stdout)
    for noisy in ("urllib3", "httpx", "httpcore", "JobSpy", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_run(a) -> int:
    from .pipeline import run
    summary = run(force=a.force, dry_run=a.dry_run, notify=not a.no_notify, lookback=a.lookback,
                  config_path=a.config, skip=tuple(a.skip or ()))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def cmd_status(a) -> int:
    from .config import ROOT, load_config
    from .state import State
    cfg = load_config(a.config)
    st = State(ROOT / "state" / "seen.json")
    print(f"última execução : {st.data.get('last_run') or '— (nunca)'}")
    d = st.days_since_last_run()
    if d is not None:
        print(f"há              : {d:.1f} dias (cadência {cfg.get('intervalo_dias', 5)} dias)")
    print(f"próxima rodada  : {'agora' if st.due(int(cfg.get('intervalo_dias', 5))) else 'ainda não'}")
    print(f"vagas conhecidas: {len(st.data['jobs'])}")
    return 0


def cmd_setup_telegram(a) -> int:
    from .config import ROOT, env, load_config
    from .notify import telegram
    load_config(a.config)
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Defina TELEGRAM_BOT_TOKEN no .env primeiro (crie o bot em @BotFather).")
        return 1
    print("Procurando conversas com o bot… (mande qualquer mensagem para ele no Telegram, se ainda não mandou)")
    chats = telegram.discover_chat_id(token)
    if not chats:
        print("Nenhuma conversa encontrada. Envie uma mensagem para o bot e rode de novo.")
        return 1
    for cid, name in chats:
        print(f"  chat_id {cid}  ({name})")
    cid = chats[0][0] if len(chats) == 1 else input("Digite o chat_id a usar: ").strip()
    telegram.write_env(ROOT / ".env", "TELEGRAM_CHAT_ID", cid)
    ok = telegram.send_message(token, cid, "✅ <b>Radar de Vagas</b> conectado. Você receberá o resumo a cada rodada.")
    print("Gravado em .env e mensagem de teste", "enviada." if ok else "FALHOU.")
    return 0 if ok else 1


def cmd_test_notify(a) -> int:
    from .config import env, load_config
    load_config(a.config)
    ctx = {"run_date_br": datetime.now().strftime("%d/%m/%Y"), "total": 1, "new_count": 1, "lookback_days": 7,
           "categorias": {"dados": {"nome": "Dados"}}, "report_url": "",
           "jobs": [{"is_new": True, "score": 88, "fit": None, "fit_note": "", "url": "https://example.com",
                     "title": "Analista de Dados Júnior (teste)", "company": "Empresa Exemplo",
                     "matched_city": "Itajaí", "workplace": "hybrid", "location": "Itajaí, SC",
                     "seniority": "junior", "category": "dados"}]}
    rc = 0
    if env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"):
        from .notify import telegram
        n = telegram.send(env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID"), ctx)
        print("telegram:", "ok" if n else "FALHOU"); rc |= int(not n)
    else:
        print("telegram: não configurado (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    if env("SMTP_USER") and env("SMTP_PASSWORD") and env("EMAIL_TO"):
        from .notify import email_
        ok = email_.send(env("SMTP_HOST", "smtp.gmail.com"), int(env("SMTP_PORT", "465")), env("SMTP_USER"),
                         env("SMTP_PASSWORD"), env("EMAIL_TO"), ctx)
        print("email:", "ok" if ok else "FALHOU"); rc |= int(not ok)
    else:
        print("email: não configurado (SMTP_USER / SMTP_PASSWORD / EMAIL_TO)")
    return rc


def cmd_render(a) -> int:
    """Regera Markdown/HTML a partir do JSON de uma rodada (útil para ajustar o layout sem coletar)."""
    from . import report
    from .config import ROOT, load_config
    cfg = load_config(a.config)
    folder = ROOT / cfg.get("relatorio", {}).get("pasta", "reports")
    path = Path(a.json_path) if a.json_path else max(folder.glob("????-??-??.json"), default=None)
    if not path or not path.exists():
        print("nenhum JSON de rodada encontrado em", folder)
        return 1
    ctx = report.load_context(path)
    paths = report.write_all(ctx, cfg)
    print("regerado:", ", ".join(str(p) for p in paths.values()))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vagas_monitor", description="Monitor de vagas — Dados/IA/Agentes/Full Stack em SC")
    p.add_argument("--config", help="caminho alternativo do config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="executa uma rodada (respeita a cadência, salvo --force)")
    r.add_argument("--force", action="store_true", help="roda mesmo antes dos 5 dias")
    r.add_argument("--dry-run", action="store_true", help="gera relatórios mas não salva estado nem notifica")
    r.add_argument("--no-notify", action="store_true", help="não envia Telegram/e-mail")
    r.add_argument("--lookback", type=int, help="janela em dias (padrão: 7; 30 na primeira execução)")
    r.add_argument("--skip", action="append", choices=["linkedin", "indeed", "gupy"], help="pula uma fonte")
    r.set_defaults(fn=cmd_run)

    sub.add_parser("status", help="mostra última execução e próxima rodada").set_defaults(fn=cmd_status)
    sub.add_parser("setup-telegram", help="descobre o chat_id do bot e grava no .env").set_defaults(fn=cmd_setup_telegram)
    sub.add_parser("test-notify", help="envia uma mensagem de teste nos canais configurados").set_defaults(fn=cmd_test_notify)
    rr = sub.add_parser("render", help="regera Markdown/HTML a partir do JSON da última rodada")
    rr.add_argument("json_path", nargs="?")
    rr.set_defaults(fn=cmd_render)

    a = p.parse_args(argv)
    _setup_logging(a.verbose)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
