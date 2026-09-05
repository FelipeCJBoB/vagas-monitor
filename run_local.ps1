# Executa uma rodada do monitor localmente (usa a venv do projeto).
# Uso:  .\run_local.ps1            -> respeita a cadência de 5 dias
#       .\run_local.ps1 --force    -> roda agora
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "venv não encontrada. Crie com:  uv venv .venv; uv pip install --python .venv -r requirements.txt"
    exit 1
}
& $py -m vagas_monitor run @args
exit $LASTEXITCODE
