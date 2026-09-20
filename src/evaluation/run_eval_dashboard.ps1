# 36 Chambers — Launcher ewaluacji i dashboardu
# Wymagania: Python 3.10+, pip, PowerShell

param(
    [string]$Golden = $env:CHAMBERS_GOLDEN_QUERIES,
    [string]$Registry = $env:CHAMBERS_REGISTRY,
    [string]$Orchestrator = $env:CHAMBERS_ORCHESTRATOR,
    [string]$OutputDir = $env:CHAMBERS_EVAL_RUN_DIR,
    [string]$SystemVersion = "shaolin-1.0",
    [string]$Model = "local-deterministic",
    [string]$PythonExe = "",
    [switch]$SkipEval,
    [switch]$OpenDashboard
)

$ErrorActionPreference = "Stop"

# 1. Wykrywanie interpretera Python (preferencja dla venv The_Buch)
if (-not $PythonExe) {
    $VenvPy = if ($env:CHAMBERS_ROOT) { Join-Path $env:CHAMBERS_ROOT "The_Buch\backend\venv\Scripts\python.exe" } else { "" }
    if (Test-Path $VenvPy) {
        $PythonExe = $VenvPy
    } else {
        $PythonExe = "python"
    }
}
Write-Host "Używany interpreter Python: $PythonExe" -ForegroundColor Cyan

# 2. Przygotowanie katalogów
$null = New-Item -ItemType Directory -Force -Path $OutputDir
$DashboardDir = Join-Path $OutputDir "dashboard"
$null = New-Item -ItemType Directory -Force -Path $DashboardDir

# 3. Ścieżki do skryptów Python
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CandidateRunners = @(
    (Join-Path $ScriptRoot "eval_runner.py"),
    (Join-Path $ScriptRoot "..\eval_runner.py")
)
$EvalRunner = $CandidateRunners | Where-Object { Test-Path $_ } | Select-Object -First 1

$DashboardPy = Join-Path $ScriptRoot "dashboard_eval.py"

if (-not $EvalRunner) {
    throw "Brak pliku eval_runner.py w lokalizacjach: $($CandidateRunners -join ', ')"
}
if (-not (Test-Path $DashboardPy)) {
    throw "Brak pliku dashboard_eval.py w katalogu: $ScriptRoot"
}

# 4. Uruchomienie ewaluacji (opcjonalnie)
$CsvPath = Join-Path $OutputDir "eval_results.csv"

if (-not $SkipEval) {
    Write-Host "Uruchamianie ewaluacji golden queries..." -ForegroundColor Cyan
    & $PythonExe $EvalRunner `
        --golden $Golden `
        --output $CsvPath `
        --orchestrator $Orchestrator `
        --registry $Registry `
        --system-version $SystemVersion `
        --model $Model `
        --reviewer auto

    if ($LASTEXITCODE -ne 0) {
        throw "Ewaluacja nie powiodła się."
    }
    Write-Host "Ewaluacja zakończona. Wynik: $CsvPath" -ForegroundColor Green
} else {
    Write-Host "Pominięto ewaluację (-SkipEval). Weryfikacja istniejącego pliku CSV..." -ForegroundColor Yellow
    if (-not (Test-Path $CsvPath)) {
        $GlobalCsv = $env:CHAMBERS_EVAL_RESULTS
        if (Test-Path $GlobalCsv) {
            Write-Host "Kopiowanie istniejącego pliku z $GlobalCsv do $CsvPath..." -ForegroundColor Cyan
            Copy-Item $GlobalCsv $CsvPath -Force
        } else {
            throw "Brak pliku eval_results.csv w: $CsvPath oraz $GlobalCsv."
        }
    }
}

# 5. Uruchomienie generatora dashboardu
Write-Host "Generowanie analityki i wykresów dashboardu..." -ForegroundColor Cyan
& $PythonExe $DashboardPy `
    --input $CsvPath `
    --output-dir $DashboardDir

if ($LASTEXITCODE -ne 0) {
    throw "Generowanie dashboardu nie powiodło się."
}

Write-Host "Dashboard pomyślnie wygenerowany w: $DashboardDir" -ForegroundColor Green

# 6. Otwarcie dashboardu w przeglądarce (opcjonalnie)
if ($OpenDashboard) {
    $AllHtml = Join-Path $DashboardDir "eval_dashboard_all.html"
    $CountHtml = Join-Path $DashboardDir "eval_count.html"
    $TargetHtml = if (Test-Path $AllHtml) { $AllHtml } else { $CountHtml }
    
    if (Test-Path $TargetHtml) {
        Write-Host "Otwieranie dashboardu w przeglądarce: $TargetHtml" -ForegroundColor Cyan
        Start-Process $TargetHtml
    } else {
        Write-Host "Nie znaleziono pliku HTML – pominięto otwieranie." -ForegroundColor Yellow
    }
}

Write-Host "Gotowe. Wszystkie operacje zakończone pomyślnie." -ForegroundColor Green
