# 금융권 공고 일일 배치 (로컬)
# 사용: .\batch\run.ps1
#       .\batch\run.ps1 -SkipFetch
#       .\batch\run.ps1 -Push

param(
    [switch]$SkipFetch,
    [switch]$Push,
    [switch]$Commit,
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$ProposalRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProposalRoot

$venvPython = Join-Path $ProposalRoot ".venv\Scripts\python.exe"
$webappVenv = Join-Path $ProposalRoot "webapp\.venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $Python = $venvPython
} elseif (Test-Path $webappVenv) {
    $Python = $webappVenv
} else {
    $Python = "python"
}

$argsList = @("-m", "batch")
if ($SkipFetch) { $argsList += "--skip-fetch" }
if ($Push) { $argsList += "--push" }
if ($Commit) { $argsList += "--commit" }
if ($Message) { $argsList += @("--message", $Message) }

Write-Host "[run.ps1] $Python $($argsList -join ' ')"
& $Python @argsList
exit $LASTEXITCODE
