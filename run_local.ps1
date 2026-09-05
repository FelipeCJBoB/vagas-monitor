# Executa uma rodada do monitor localmente (usa a venv do projeto) e sincroniza com o GitHub.
# Uso:  .\run_local.ps1            -> respeita a cadência de 5 dias
#       .\run_local.ps1 --force    -> roda agora
#
# Se o repositório tiver um remoto `origin`, faz `git pull` antes e commita/pusha os
# relatórios depois — assim o estado (state/seen.json) fica igual ao do GitHub Actions
# e as duas formas de agendamento não duplicam notificações.
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv não encontrada. Crie com:  uv venv .venv --python 3.10; uv pip install --python .venv -r requirements.txt"
    exit 1
}
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null
$log = Join-Path $PSScriptRoot ("logs\" + (Get-Date -Format "yyyy-MM-dd_HHmm") + ".log")

$hasGit = $false
if (Test-Path (Join-Path $PSScriptRoot ".git")) {
    git remote get-url origin *> $null
    if ($LASTEXITCODE -eq 0) { $hasGit = $true }
}
if ($hasGit) { git pull --rebase --quiet *> $null }

$env:PYTHONIOENCODING = "utf-8"
& $py -m vagas_monitor run @args *> $log
$rc = $LASTEXITCODE
Get-Content $log | Select-Object -Last 25

if ($rc -eq 0 -and $hasGit) {
    git add reports docs state *> $null
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit --quiet -m ("relatório local " + (Get-Date -Format "yyyy-MM-dd")) *> $null
        git push --quiet *> $null
    }
}
exit $rc
