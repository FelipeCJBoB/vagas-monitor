"""Isolamento dos testes em relação ao ambiente real.

`load_config` chama `load_dotenv`, que lê o `.env` do repositório. Como o arquivo
tem token do Telegram e chave da API, qualquer teste que exercite o pipeline
completo passava a mandar mensagem de verdade e a gastar crédito — e só começava
a fazer isso depois que o `.env` fosse preenchido, o que esconde o problema de
quem escreveu o teste.

A fixture abaixo vale para todos os testes: neutraliza a leitura do `.env` e apaga
as variáveis que ligam efeitos externos. Um teste que precise delas deve declará-las
explicitamente com `monkeypatch.setenv`.
"""
import pytest

from vagas_monitor import config

EFEITOS_EXTERNOS = (
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO",
    "REPORT_URL",
)


@pytest.fixture(autouse=True)
def ambiente_isolado(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: False)
    for nome in EFEITOS_EXTERNOS:
        monkeypatch.delenv(nome, raising=False)
