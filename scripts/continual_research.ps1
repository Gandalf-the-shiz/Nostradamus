# Research controller — OBSERVE → HYPOTHESIZE → EXPERIMENT → DECIDE (every 30 min).
param(
    [int]$IntervalMinutes = 30,
    [int]$ErrorCooldownSec = 120
)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptRoot
$Paused     = Join-Path $RepoRoot "data\PAUSED.txt"
$LogDir     = Join-Path $RepoRoot "logs"
$log        = Join-Path $LogDir "research-controller.log"

$Python = "C:\Users\nicho\AppData\Local\Programs\Python\Python311-arm64\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:PYTHONPATH = Join-Path $RepoRoot "scripts"
Set-Location $RepoRoot

$loadEnvScript = Join-Path $ScriptRoot "load_repo_env.ps1"
if (Test-Path $loadEnvScript) {
    . $loadEnvScript -RepoRoot $RepoRoot
}

function Log($m) {
    $line = "$((Get-Date).ToString('s'))  $m"
    $line | Tee-Object -FilePath $log -Append
}

Log "[research] controller loop online (interval=${IntervalMinutes}m, PID $PID)"
try {
    $backend = & $Python -c "from app_secrets import load_secrets; load_secrets(); from intelligence.research_reasoner import resolve_llm_backend; print(resolve_llm_backend())" 2>$null
    if ($backend) { Log "[research] LLM backend: $backend" }
} catch {
    Log "[research] LLM backend: unknown (could not resolve)"
}

while ($true) {
    if (Test-Path $Paused) {
        Log "[research] PAUSED.txt present — sleeping 10m"
        Start-Sleep -Seconds 600
        continue
    }
    try {
        Log "[research] tick start"
        & $Python "scripts\intelligence\research_controller.py" "--tick" 2>&1 | ForEach-Object { Log "  $_" }
        Log "[research] tick done; sleeping ${IntervalMinutes}m"
        Start-Sleep -Seconds ([Math]::Max(60, $IntervalMinutes * 60))
    } catch {
        Log "[research] error: $_"
        Start-Sleep -Seconds $ErrorCooldownSec
    }
}
