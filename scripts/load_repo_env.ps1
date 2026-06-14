# Load repo .env + config/secrets.json into process env (existing env vars win).
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

function Import-RepoEnv {
    param([string]$Root)

    $dotenv = Join-Path $Root ".env"
    if (Test-Path $dotenv) {
        Get-Content $dotenv -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if (-not $line -or $line.StartsWith("#")) { return }
            if ($line.StartsWith("export ")) { $line = $line.Substring(7).Trim() }
            $eq = $line.IndexOf("=")
            if ($eq -lt 1) { return }
            $name = $line.Substring(0, $eq).Trim()
            $val = $line.Substring($eq + 1).Trim()
            if ($val.Length -ge 2 -and $val[0] -eq $val[-1] -and ($val[0] -eq '"' -or $val[0] -eq "'")) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            if ($name -and -not (Get-Item -Path "Env:$name" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$name" -Value $val
            }
        }
    }

    $secrets = Join-Path $Root "config\secrets.json"
    if (Test-Path $secrets) {
        try {
            $doc = Get-Content $secrets -Raw -Encoding UTF8 | ConvertFrom-Json
            $doc.PSObject.Properties | ForEach-Object {
                if ($_.Name -notmatch '^_' -and $_.Value -and -not (Get-Item -Path "Env:$($_.Name)" -ErrorAction SilentlyContinue)) {
                    Set-Item -Path "Env:$($_.Name)" -Value ([string]$_.Value)
                }
            }
        } catch {
            Write-Warning "[env] could not read secrets.json: $_"
        }
    }
}

Import-RepoEnv -Root $RepoRoot
