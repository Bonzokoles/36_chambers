# 36 Chambers Knowledge Observatory launcher
param(
 [string]$Registry=$env:CHAMBERS_REGISTRY,
 [string]$Db=$env:CHAMBERS_OBSERVATORY_SQLITE,
 [string]$OutDir=$env:CHAMBERS_OBSERVATORY_DASHBOARD,
 [string]$EventLog="",
 [string]$PythonExe="",
 [switch]$OpenDashboard
)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Wybór interpretera Python
if (-not $PythonExe) {
    $VenvPy = if ($env:CHAMBERS_ROOT) { Join-Path $env:CHAMBERS_ROOT "The_Buch\backend\venv\Scripts\python.exe" } else { "" }
    if (Test-Path $VenvPy) {
        $PythonExe = $VenvPy
    } else {
        $PythonExe = "python"
    }
}
Write-Host "Używany interpreter Python: $PythonExe" -ForegroundColor Cyan

# 2. Snapshot inwentarza wiedzy
Write-Host "Tworzenie migawki inwentarza wiedzy (metadata-only)..." -ForegroundColor Cyan
& $PythonExe "$root\knowledge_inventory_scan.py" --registry $Registry --db $Db
if ($LASTEXITCODE -ne 0) { throw "Błąd skanowania inwentarza" }

# 3. Import telemetrii zdarzeń (jeśli wskazana lub domyślna istnieje)
if (-not $EventLog) {
    $DefaultLog = $env:CHAMBERS_OBSERVATORY_EVENTS
    if ($DefaultLog -and (Test-Path $DefaultLog)) {
        $EventLog = $DefaultLog
    }
}
if ($EventLog -and (Test-Path $EventLog)) {
    Write-Host "Importowanie telemetrii zdarzeń z $EventLog..." -ForegroundColor Cyan
    & $PythonExe "$root\import_observatory_events.py" --log $EventLog --db $Db
    if ($LASTEXITCODE -ne 0) { throw "Błąd importu telemetrii" }
}

# 4. Generowanie analityki i dashboardu HTML
Write-Host "Generowanie panelu Knowledge Observatory..." -ForegroundColor Cyan
& $PythonExe "$root\knowledge_observatory_dashboard.py" --db $Db --out-dir $OutDir
if ($LASTEXITCODE -ne 0) { throw "Błąd generowania dashboardu" }

# 5. Otwarcie w przeglądarce
if ($OpenDashboard) {
    $AllHtml = Join-Path $OutDir "observatory_all.html"
    $TargetHtml = if (Test-Path $AllHtml) { $AllHtml } else { Join-Path $OutDir "knowledge_assets.html" }
    Write-Host "Otwieranie dashboardu w przeglądarce: $TargetHtml" -ForegroundColor Cyan
    Start-Process $TargetHtml
}

Write-Host "Ukończono pomyślnie: $OutDir" -ForegroundColor Green
