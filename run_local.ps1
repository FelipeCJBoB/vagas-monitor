# Execução MANUAL de uma rodada do monitor.
#
# O agendamento de produção é o GitHub Actions (.github/workflows/monitor.yml).
# Este script existe para rodar sob demanda e depurar localmente; NÃO o coloque
# no Agendador de Tarefas. Dois agendadores gravando o mesmo state/seen.json
# duplicam notificações e divergem o repositório.
#
# Uso:  .\run_local.ps1            -> respeita a cadência de 5 dias
#       .\run_local.ps1 --force    -> roda agora
#       .\run_local.ps1 --no-notify --dry-run  -> ensaio sem efeitos

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv nao encontrada. Crie com:  uv venv .venv --python 3.10; uv pip install --python .venv -r requirements.txt"
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null
$log = Join-Path $PSScriptRoot ("logs\" + (Get-Date -Format "yyyy-MM-dd_HHmm") + ".log")

# --- git: so continua se a arvore estiver limpa e sincronizada -------------
$hasGit = $false
if (Test-Path (Join-Path $PSScriptRoot ".git")) {
    git remote get-url origin *> $null
    if ($LASTEXITCODE -eq 0) { $hasGit = $true }
}

if ($hasGit) {
    if (Test-Path (Join-Path $PSScriptRoot ".git\rebase-merge")) {
        Write-Host "ABORTADO: rebase em andamento. Resolva com 'git rebase --continue' ou 'git rebase --abort'."
        exit 1
    }
    $sujo = git status --porcelain -- reports docs state
    if ($sujo) {
        Write-Host "ABORTADO: ha alteracoes nao commitadas em reports/docs/state:"
        Write-Host $sujo
        Write-Host "Commite ou descarte antes de rodar, para nao misturar com o resultado desta rodada."
        exit 1
    }
    git pull --rebase --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ABORTADO: 'git pull --rebase' falhou (exit $LASTEXITCODE). O Actions provavelmente publicou uma rodada."
        Write-Host "Resolva o repositorio antes de rodar de novo."
        exit 1
    }
}

# --- rodada ----------------------------------------------------------------
$env:PYTHONIOENCODING = "utf-8"
& $py -m vagas_monitor run @args *> $log
$rc = $LASTEXITCODE
Get-Content $log | Select-Object -Last 25

if ($rc -ne 0) {
    Write-Host "A rodada falhou (exit $rc). Log completo em: $log"
    exit $rc
}

# --- publicacao ------------------------------------------------------------
if ($hasGit) {
    git add reports docs state *> $null
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        # -F com arquivo UTF-8: passar acentos direto no -m corrompe a mensagem no console do Windows
        $msg = Join-Path $env:TEMP "vagas-commit-msg.txt"
        [System.IO.File]::WriteAllText($msg, "relatorio local " + (Get-Date -Format "yyyy-MM-dd"), (New-Object System.Text.UTF8Encoding $false))
        git commit --quiet -F $msg
        Remove-Item $msg -ErrorAction SilentlyContinue
        git push --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "AVISO: 'git push' falhou (exit $LASTEXITCODE). O commit local existe;"
            Write-Host "rode 'git pull --rebase' e 'git push' manualmente para nao divergir do Actions."
            exit 1
        }
    }
}
exit 0
