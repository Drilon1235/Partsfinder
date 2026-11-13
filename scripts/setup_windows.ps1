# Partsfinder - installation on Windows
# Easiest: double-click setup_windows.bat in the project folder.
# - installs Python 3.12 via winget if missing
# - creates backend\.venv and installs all packages
# - checks the environment and runs the tests
# Everything is also written to backend\setup_log.txt

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
Start-Transcript -Path (Join-Path $backend "setup_log.txt") -Force | Out-Null

function Find-Python {
    foreach ($v in @("3.12", "3.11")) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py "-$v" -c "import sys" *> $null   # discard output, otherwise it becomes part of the result
            if ($LASTEXITCODE -eq 0) { return , @("py", "-$v") }
        }
        $exe = Join-Path $env:LOCALAPPDATA ("Programs\Python\Python" + $v.Replace(".", "") + "\python.exe")
        if (Test-Path $exe) { return , @($exe) }
    }
    return $null
}

try {
    Set-Location $backend

    $py = Find-Python
    if (-not $py) {
        Write-Host "Python 3.12 not found: installing via winget..." -ForegroundColor Yellow
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget is missing. Install Python 3.12 from https://www.python.org/downloads/ and start again."
        }
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $py = Find-Python
        if (-not $py) {
            throw "Python does not seem to be installed. Close this window and double-click setup_windows.bat again."
        }
    }
    $pyExe = $py[0]
    $pyArgs = @($py | Select-Object -Skip 1)
    Write-Host "Python found: $($py -join ' ')" -ForegroundColor Green

    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment..."
        & $pyExe @pyArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "creating venv failed" }
    }

    $python = Join-Path $backend ".venv\Scripts\python.exe"
    Write-Host "Installing packages (first time 5-10 minutes)..."
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (see the messages above)" }

    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "backend\.env created: fill in your ANTHROPIC_API_KEY there later." -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Check, tests and test data (result also in backend\check_log.txt)..."
    & $python run_checks.py --testdata --import --eval
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}
finally {
    Stop-Transcript | Out-Null
}
