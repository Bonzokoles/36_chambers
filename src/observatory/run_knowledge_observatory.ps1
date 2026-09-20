# 36 Chambers Knowledge Observatory launcher
param(
 [string]$Registry="Z:\36_chambers\.doc\36_CHAMBERS_REGISTRY.json",
 [string]$Db="Z:\36_chambers\.doc\observatory\knowledge_observatory.sqlite",
 [string]$OutDir="Z:\36_chambers\.doc\observatory\dashboard",
 [string]$EventLog="",
 [string]$PythonExe="",
 [switch]$OpenDashboard
)
$ErrorActionPreference="Stop"
$root=Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Wybór interpretera Python
if (-not $PythonExe) {
    $VenvPy = "Z:\36_chambers\The_Buch\backend\venv\Scripts\python.exe"
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
    $DefaultLog = "Z:\36_chambers\.doc\observatory\events\events.jsonl"
    if (Test-Path $DefaultLog) {
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
