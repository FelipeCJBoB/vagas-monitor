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
   deduplica: id do ATS (exato) → chave título+empresa → tokens (dedupe.py)
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

**Painel público:** <https://felipecjbob.github.io/vagas-monitor/> (GitHub Pages, branch `main`, pasta `/docs`;
atualizado automaticamente a cada rodada).

### Agendador único

**O GitHub Actions é o único agendador.** Não registre `run_local.ps1` no Agendador de
Tarefas do Windows. Os dois leem e gravam o mesmo `state/seen.json`, que trafega pelo
repositório: numa rodada em que as janelas se cruzem, ambos enxergam a cadência vencida,
executam a coleta inteira, mandam a mesma notificação duas vezes e disputam o `git push`.
O perdedor fica com um commit local que ninguém envia, e o repositório diverge em silêncio.

Para rodar sob demanda, use o script manualmente:

```powershell
.\run_local.ps1 --force
```

Ele agora aborta se houver rebase pendente ou alteração não commitada em `reports`,
`docs` ou `state`, e avisa em vez de engolir uma falha de `pull` ou `push`.

## Telegram em 2 minutos

1. No Telegram, abra **@BotFather** → `/newbot` → copie o token para `TELEGRAM_BOT_TOKEN` no `.env`.
2. Mande qualquer mensagem para o bot recém-criado.
3. `python -m vagas_monitor setup-telegram` — descobre o chat id, grava no `.env` e envia um teste.

## E-mail (Gmail)

Ative a verificação em 2 etapas e gere uma **senha de app** em
<https://myaccount.google.com/apppasswords>. Preencha `SMTP_USER`, `SMTP_PASSWORD` e `EMAIL_TO` no `.env`.

## Tecnologias mais pedidas

Cada rodada conta **em quantas vagas cada tecnologia aparece**, uma vez por vaga, e
ranqueia pela contagem. Sem peso nem filtro de perfil: é a demanda crua do mercado. Sai
em todos os canais: tabela no Markdown, aba no painel, as dez primeiras no Telegram e
quinze no e-mail.

- **Extração no momento da coleta**, sobre a descrição completa de cada vaga. As do
  LinkedIn são buscadas uma a uma, porque o card da busca não traz descrição.
- **Uma tecnologia por item** no `skills.yaml`: React, PostgreSQL, RAG, pgvector, e não
  "Front-end" ou "Banco de dados". Os termos de um item são só grafias da mesma coisa;
  pandas não conta como Python.
- **Termo com `=` na frente respeita maiúsculas**, para nomes que também são palavras
  comuns em inglês: `=React` não casa com "react quickly", `=SOLID` não casa com "solid
  experience".
- **No painel, o ranking obedece aos filtros da barra lateral** (categoria, local, nível,
  busca). "Ver vagas" em qualquer linha abre a lista filtrada por aquela tecnologia.
- Só vagas com descrição entram na base; o painel diz quantas ficaram de fora.

Mudou o `skills.yaml`? `python -m vagas_monitor render` refaz o ranking da última rodada
sem coletar de novo, porque o JSON guarda a descrição inteira.

## Avaliação por IA (opcional)

Com uma chave configurada, as melhores vagas novas de cada rodada recebem nota de 0 a 10
e um comentário. São dois provedores, e `avaliacao.provedor: auto` usa o primeiro que
encontrar chave, preferindo o Gemini.

| | Gemini (Google AI Studio) | Claude (Anthropic) |
|---|---|---|
| Custo | nível gratuito permanente | pré-pago, ~US$ 0,30 por rodada |
| Onde pegar a chave | <https://aistudio.google.com/apikey> | <https://console.anthropic.com> |
| Limite | por minuto (10 RPM no Flash) | pelo saldo da conta |
| Privacidade | no nível gratuito, o Google pode usar os dados para treinar | não usa para treinar |
| Variável | `GEMINI_API_KEY` | `ANTHROPIC_API_KEY` |

**A assinatura não dá a chave.** Nem o Gemini Pro (Google One AI Premium) nem o plano do
Claude.ai incluem acesso à API: são cobranças separadas. No caso do Google, a chave do AI
Studio é gratuita para qualquer conta, com ou sem assinatura, então o efeito prático é o
mesmo, só que pelo motivo certo.

Sobre a privacidade do nível gratuito do Gemini: o que trafega são anúncios de vaga, que
já são públicos, e o `perfil.md`, que está neste repositório público. Quem ainda assim
preferir que não seja usado para treino deve ativar cobrança na conta Google ou usar
`provedor: anthropic`.

O volume desta automação é de 25 chamadas a cada 5 dias, bem dentro do gratuito. As
chamadas são espaçadas conforme `avaliacao.gemini.rpm` para não esbarrar no limite por
minuto: 25 vagas a 10 RPM levam pouco mais de dois minutos, irrelevante numa rodada que
já gasta doze minutos coletando.

Para validar a chave sem esperar a próxima rodada:

```powershell
.\.venv\Scripts\python -m vagas_monitor check-ia
```

Ele mostra quais chaves encontrou, qual provedor usaria, e faz uma chamada real com uma
vaga de exemplo.

Se a avaliação falhar, a rodada segue sem as notas e o motivo aparece no topo do relatório
e do painel. O monitor desiste após 3 falhas seguidas, e imediatamente quando o erro é
definitivo (chave inválida, saldo zerado, modelo inexistente).

O teto é `avaliacao.max_vagas`, 25 por padrão, aplicado às vagas novas de maior pontuação.
A legenda da estrela informa quantas foram avaliadas, e some quando não houve nenhuma.

## Ajustando o alvo

Tudo em `config.yaml`: cidades, termos de busca, palavras que definem cada categoria,
listas de senioridade, skills do currículo, `top_n`, canais. `perfil.md` alimenta a
avaliação por IA. Nada disso exige mexer no código.

### Como a taxonomia foi calibrada

As categorias não saíram de intuição. Em setembro de 2026 comparamos o que o monitor
capturava com as vagas em que o Felipe efetivamente se candidatou, e o resultado mostrou
o ponto cego:

| Vaga | O que acontecia |
|---|---|
| Implantador de Sistemas, SENSUM, Itajaí | nenhuma regra classificava; nunca apareceu em rodada alguma |
| Analista SAP SD e SAP MM, Jaraguá do Sul | descartadas, apesar de SAP ser o uso diário dele na TKMS |
| Analista DevOps Pleno | descartada |

Daí nasceram as categorias `sistemas_negocio` e `devops_auto`, com prioridade baixa para
entrarem no radar sem disputar o topo com Dados e IA, mais os termos de busca `SAP`,
`analista de sistemas` e `devops`.

O método vale para repetir: quando uma vaga interessante aparecer fora do relatório,
rode o título por `filters.classify` e veja se alguma regra pega. Se não pegar, o que
falta é um termo, não mais uma fonte.

Duas armadilhas que essa expansão trouxe e já estão tratadas em `excluir_titulo`:
segurança do trabalho não é segurança da informação, e agente de negócios não é agente de IA.

A seção `estado` controla a memória entre rodadas:

| Chave | Padrão | O que faz |
|---|---:|---|
| `key_ttl_days` | 30 | Tempo em que o par título+empresa ainda é tratado como a mesma vaga. Passado o prazo, uma posição reaberta volta a ser anunciada. |
| `keep_days` | 120 | Tempo que o registro de uma vaga sobrevive em `state/seen.json`. |

## Fontes e limites conhecidos

- **LinkedIn**: endpoint público de convidado (10 vagas/página). Em IPs de nuvem pode devolver
  429 ocasionalmente — o coletor espera e tenta de novo; a rodada segue com as outras fontes.
- **Indeed**: via `python-jobspy`; traz descrição completa. Às vezes publica sem o nome da
  empresa. Quando o link de candidatura aponta para o ATS dela (`empresa.gupy.io`,
  `empresa.vagas.solides.com.br`), o nome é inferido do subdomínio e marcado como inferido;
  quando não há de onde tirar, o card diz "Empresa não informada".
- **Gupy**: API JSON do portal; traz descrição completa e é a mais usada por empresas de SC.
  O `jobId` do link vale como identidade exata: a mesma vaga vinda pelo Indeed casa com a da
  Gupy sem depender de comparar textos.
- Glassdoor/Catho/Google Jobs não são cobertos (bloqueio ou sem localização por cidade).
