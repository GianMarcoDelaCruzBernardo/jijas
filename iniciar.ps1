param([switch]$Background)
$ErrorActionPreference = "Stop"
$pro = "C:\FootballAI\Pro"; $py = "C:\FootballAI\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
foreach ($p in 8766,8888,8889) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match "footballai_(pro|web)" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 1
New-Item -ItemType Directory -Force "$pro\logs" | Out-Null
if (-not (Test-Path "$pro\ui.html")) { throw "Falta ui.html en $pro" }
if ((Get-Content "$pro\footballai_pro.py" -Raw -Encoding UTF8) -notmatch "def live_analysis") { throw "footballai_pro.py NO es la version nueva" }
& $py -m py_compile "$pro\footballai_pro.py"; if ($LASTEXITCODE -ne 0) { throw "Error de sintaxis en footballai_pro.py" }
if ($Background) {
  Start-Process $py -ArgumentList "footballai_pro.py" -WorkingDirectory $pro -WindowStyle Hidden -RedirectStandardOutput "$pro\logs\server_out.log" -RedirectStandardError "$pro\logs\server_err.log"
} else { Start-Process $py -ArgumentList "footballai_pro.py" -WorkingDirectory $pro }
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep 1
  try { if ((Invoke-WebRequest "http://127.0.0.1:8888/" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { Write-Host "OK: Football AI Pro (22 modelos) en http://127.0.0.1:8888" -ForegroundColor Green; exit 0 } } catch {}
}
Write-Host "No respondio en 20 s. Revisa $pro\logs\server_err.log" -ForegroundColor Red; exit 1