# Windows PowerShell. Dùng:  .\run.ps1 setup | doctor | pg-setup | start | seed | stop | status | reset-demo --yes | test
# Nếu bị chặn chạy script: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Cmd)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$onWindows = ($PSVersionTable.PSEdition -eq "Desktop") -or $IsWindows
$venvPy = if ($onWindows) { Join-Path $PSScriptRoot ".venv\Scripts\python.exe" } else { Join-Path $PSScriptRoot ".venv/bin/python" }

function Find-Python {
    if ($env:PYTHON) { return @($env:PYTHON) }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @("py", "-3") }
    if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return @("python3") }
    throw "Không tìm thấy Python 3.11+. Cài từ https://www.python.org/downloads/ (tick 'Add python.exe to PATH')."
}

if (-not $Cmd -or $Cmd.Count -eq 0) {
    Write-Host "Dùng: .\run.ps1 setup | doctor | pg-setup | start | seed | stop | status | reset-demo --yes | test"; exit 1
}
switch ($Cmd[0]) {
    "setup" {
        $py = @(Find-Python)          # @() giữ dạng mảng khi chỉ có 1 phần tử
        $exe = $py[0]; $pre = @(); if ($py.Count -gt 1) { $pre = $py[1..($py.Count - 1)] }
        & $exe @pre -m venv .venv
        & $venvPy -m pip install --upgrade pip | Out-Null
        & $venvPy -m pip install -r requirements.txt
        & $venvPy manage.py init-env
        & $venvPy manage.py build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $venvPy manage.py init-db
        & $venvPy manage.py doctor
        Write-Host "Tiếp theo: tạo DB PostgreSQL (.\run.ps1 pg-setup hoặc docker compose, xem README), rồi .\run.ps1 start và .\run.ps1 seed"
    }
    "test" {
        & $venvPy -m pip install -r requirements-dev.txt | Out-Null
        & $venvPy manage.py test-services
        & $venvPy -m pytest tests/unit tests/integration tests/e2e
        exit $LASTEXITCODE
    }
    default {
        if (-not (Test-Path $venvPy)) { Write-Host "Chưa cài đặt, chạy .\run.ps1 setup trước"; exit 1 }
        & $venvPy manage.py @Cmd
        exit $LASTEXITCODE
    }
}
