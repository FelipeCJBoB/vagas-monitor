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

## O que o mercado cobra

Cada rodada lê as descrições das vagas e monta um mapa de habilidades separando
**presencial ou híbrido na região** de **remoto nacional**. Ele sai em todos os canais:
tabela completa no Markdown e no painel, resumo das três prioridades no Telegram, seis
no e-mail.

A separação existe porque os dois não são o mesmo mercado com endereços diferentes. A
região é indústria com ERP e BI consolidados; o remoto é empresa de tecnologia com stack
de nuvem. Uma lista média dos dois não descreve nenhum dos dois, e leva a estudar a coisa
errada.

A ordem de prioridade não é a frequência bruta. É **quanto cada habilidade destrava de
vagas que você pode pegar hoje**, ou seja, júnior, pleno ou sem nível declarado,
descontando o que já domina. O que você já sabe aparece no mapa marcado como domínio,
para lembrar de destacar no currículo, mas fica fora da lista de estudo.

Três salvaguardas contra ler tendência onde só há ruído:

| Guarda | Efeito |
|---|---|
| `min_ocorrencias` no `skills.yaml` | habilidade com menos de 4 menções não entra |
| mínimo de 10 vagas por segmento | abaixo disso a coluna "onde pesa" é neutralizada e o relatório avisa |
| só vagas com descrição no denominador | evita que toda habilidade pareça mais rara do que é |

A comparação entre os segmentos mistura duas causas: vagas remotas vêm de empresas de
tecnologia e tendem a ser mais sêniores, então parte da diferença é o tipo de empresa, não
o regime de trabalho. O relatório informa o tamanho da amostra ao lado de cada número.

Edite o campo `tenho` do `skills.yaml` conforme for estudando (`sim`, `parcial`, `nao`) e a
prioridade se recalcula sozinha na rodada seguinte.

## Avaliação por IA (opcional)

Com `ANTHROPIC_API_KEY` no `.env` e nos segredos do repositório, as melhores vagas novas
de cada rodada recebem nota de 0 a 10 e um comentário. Dois pontos que custam uma rodada
se passarem despercebidos:

- **A chave sozinha não basta: a conta precisa de crédito.** Sem saldo, a API responde 400
  e nenhuma vaga é avaliada. O monitor desiste após 3 falhas seguidas, em vez de repetir o
  erro 25 vezes, e o motivo aparece no topo do relatório e do painel.
- O teto é `claude.max_vagas` (25 por padrão), aplicado às vagas novas de maior pontuação.
  A legenda da estrela diz quantas foram avaliadas, e some quando não houve nenhuma.

Custo aproximado com o padrão atual: cerca de US$ 0,30 por rodada. Trocar `claude.modelo`
para `claude-sonnet-5` reduz para uns 20% disso.

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
