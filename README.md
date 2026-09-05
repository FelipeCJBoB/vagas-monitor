# Radar de Vagas — Vale do Itajaí / Norte de SC

Automação que, **a cada 5 dias**, varre LinkedIn, Indeed e Gupy atrás de vagas de
**Agentes de IA · Dados · IA/LLMs · Full Stack** em Itajaí, Navegantes, Balneário Camboriú,
Gaspar, Blumenau, Joinville, Jaraguá do Sul e Brusque (mais vagas 100 % remotas no Brasil),
pontua cada uma contra o perfil em `perfil.md`, e entrega:

| Canal | O que chega | Configuração |
|---|---|---|
| **Markdown** | `reports/AAAA-MM-DD.md` + `reports/LATEST.md` | nenhuma (sempre gerado) |
| **Painel HTML** | `docs/index.html` (filtros por categoria/cidade/nível) | nenhuma; vira site com GitHub Pages |
| **Telegram** | resumo das melhores vagas novas, com link | token do bot + chat id |
| **E-mail** | tabela das novas + Markdown anexo | senha de app do Gmail |
| **Claude (opcional)** | nota 0–10 e comentário por vaga nova | `ANTHROPIC_API_KEY` |

Só aparecem vagas **novas** (não vistas em rodadas anteriores) nas notificações; o relatório
completo mantém tudo que está na janela.

## Como funciona

```
termos_busca × (3 cidades-âncora LinkedIn | Santa Catarina Indeed | estado=SC Gupy) + remotas
        │
        ▼  coleta (sources/)              ~5–8 min por rodada, sem login
   deduplica (mesma vaga em 2 fontes)
        │
        ▼  filters.py
   cidade-alvo? remoto?  →  categoria (título/descrição)  →  senioridade
        │
        ▼  scoring.py  (0–100, regras explícitas e auditáveis)
   +30 categoria no título · +25 júnior/estágio · +20 cidade-alvo · +12 remoto
   +até 18 skills do currículo · −30 sênior/liderança · +5 publicada ≤7 dias
        │
        ▼  state/seen.json  (o que já foi visto; cadência de 5 dias)
        ▼  enrich_claude.py (opcional)  →  report.py (md/json/html)  →  notify/
```

## Rodando localmente

```powershell
uv venv .venv --python 3.10
uv pip install --python .venv -r requirements.txt
.\.venv\Scripts\python -m vagas_monitor run --force      # primeira rodada (janela de 30 dias)
.\.venv\Scripts\python -m vagas_monitor status           # quando é a próxima
.\.venv\Scripts\pytest -q                                # testes
```

Outros comandos: `run --dry-run` (não salva estado nem notifica), `run --skip linkedin`,
`run --lookback 14`, `render` (regera md/html do último JSON sem coletar), `test-notify`.

## Agendamento (GitHub Actions — recomendado)

O workflow em `.github/workflows/monitor.yml` roda **todo dia às 08:00 (Brasília)**; o
script só executa de fato quando passaram 5 dias da última rodada (registro em
`state/seen.json`, que é commitado). Relatórios e painel são commitados no repositório.
Não precisa de PC ligado.

Segredos (Settings → Secrets → Actions, ou via CLI):

```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set SMTP_USER --body felipefilipi1213@gmail.com
gh secret set SMTP_PASSWORD
gh secret set EMAIL_TO --body felipefilipi1213@gmail.com
gh secret set ANTHROPIC_API_KEY      # opcional
```

Rodar manualmente: aba **Actions → Monitor de vagas → Run workflow**.

**Painel público:** com o repositório público, ative *Settings → Pages → Branch `main` / pasta `/docs`*.
O painel ficará em `https://felipecjbob.github.io/vagas-monitor/`.

### Alternativa: Agendador de Tarefas do Windows

```powershell
schtasks /Create /TN "Radar de Vagas" /SC DAILY /ST 08:30 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"$PWD\run_local.ps1\"" /F
```

(Roda todo dia; o script respeita a cadência de 5 dias. Se usar as duas formas ao mesmo
tempo, o estado local e o do GitHub divergem — escolha uma.)

## Telegram em 2 minutos

1. No Telegram, abra **@BotFather** → `/newbot` → copie o token para `TELEGRAM_BOT_TOKEN` no `.env`.
2. Mande qualquer mensagem para o bot recém-criado.
3. `python -m vagas_monitor setup-telegram` — descobre o chat id, grava no `.env` e envia um teste.

## E-mail (Gmail)

Ative a verificação em 2 etapas e gere uma **senha de app** em
<https://myaccount.google.com/apppasswords>. Preencha `SMTP_USER`, `SMTP_PASSWORD` e `EMAIL_TO` no `.env`.

## Ajustando o alvo

Tudo em `config.yaml`: cidades, termos de busca, palavras que definem cada categoria,
listas de senioridade, skills do currículo, `top_n`, canais. `perfil.md` alimenta a
avaliação por IA. Nada disso exige mexer no código.

## Fontes e limites conhecidos

- **LinkedIn**: endpoint público de convidado (10 vagas/página). Em IPs de nuvem pode devolver
  429 ocasionalmente — o coletor espera e tenta de novo; a rodada segue com as outras fontes.
- **Indeed**: via `python-jobspy`; traz descrição completa.
- **Gupy**: API JSON do portal; traz descrição completa e é a mais usada por empresas de SC.
- Glassdoor/Catho/Google Jobs não são cobertos (bloqueio ou sem localização por cidade).
