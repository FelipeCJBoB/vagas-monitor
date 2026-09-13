"""Isolamento dos testes em relação ao ambiente real.

`load_config` chama `load_dotenv`, que lê o `.env` do repositório. O arquivo tem
token do Telegram e chaves de API, então qualquer teste que exercite o pipeline
completo passa a mandar mensagem de verdade e a gastar cota — e só começa a fazer
isso depois que o `.env` for preenchido, bem depois de o teste ter sido escrito.

Duas armadilhas já pisadas aqui:

1. Neutralizar `load_dotenv` numa fixture de escopo de FUNÇÃO não basta. Fixtures
   de escopo maior são montadas antes, então a `cfg` de escopo de módulo em
   `test_filters.py` chamava `load_config` com o `load_dotenv` verdadeiro e
   despejava o `.env` inteiro em `os.environ`, de onde ele não sai mais. Por isso
   o remendo é de escopo de SESSÃO.

2. Listar as variáveis à mão deixa buraco a cada provedor novo: o `GEMINI_API_KEY`
   entrou e ficou de fora da lista, e a suíte voltou a bater na API de verdade,
   gastando 55 segundos por rodada de testes. Agora a lista é derivada dos
   próprios provedores registrados.
"""
import pytest

from vagas_monitor import config
from vagas_monitor.providers import DISPONIVEIS

# Derivadas do código, não escritas à mão: provedor novo entra aqui sozinho.
CHAVES_DE_IA = tuple(mod.ENV_VAR for mod in DISPONIVEIS.values())

EFEITOS_EXTERNOS = CHAVES_DE_IA + (
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO",
    "REPORT_URL",
)


@pytest.fixture(scope="session", autouse=True)
def sem_dotenv():
    """Impede que o `.env` chegue a `os.environ`, inclusive via fixture de módulo."""
    original = config.load_dotenv
    config.load_dotenv = lambda *a, **k: False
    yield
    config.load_dotenv = original


@pytest.fixture(autouse=True)
def ambiente_isolado(monkeypatch):
    for nome in EFEITOS_EXTERNOS:
        monkeypatch.delenv(nome, raising=False)
