param(
    [switch]$InstallDependencies
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPath = Join-Path $ProjectRoot 'backend'
$FrontendPath = Join-Path $ProjectRoot 'frontend'
$BackendPython = Join-Path $BackendPath '.venv\Scripts\python.exe'

if (-not (Test-Path $BackendPython)) {
    throw "Backend virtual environment not found: $BackendPython"
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'npm was not found. Please install Node.js first.'
}

if ($InstallDependencies) {
    Write-Host 'Installing backend dependencies from the domestic mirror...'
    & $BackendPython -m pip install -r (Join-Path $BackendPath 'requirements.txt') --index-url https://mirrors.aliyun.com/pypi/simple
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    Write-Host 'Installing frontend dependencies...'
    & npm.cmd --prefix $FrontendPath ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
}

foreach ($ServicePort in 8000, 5173) {
    $Listener = Get-NetTCPConnection -LocalPort $ServicePort -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in '127.0.0.1', '0.0.0.0', '::', '::1' }
    if ($Listener) {
        throw "Port $ServicePort is occupied by PID $($Listener.OwningProcess -join ', '). Stop that service before retrying."
    }
}

$BackendCommand = "`$Host.UI.RawUI.WindowTitle = 'PaperReader - Backend'; & '.\backend\.venv\Scripts\python.exe' -m uvicorn backend.main:create_app --factory --reload --reload-dir backend --host 127.0.0.1 --port 8000"
$FrontendCommand = "`$Host.UI.RawUI.WindowTitle = 'PaperReader - Frontend'; npm.cmd run dev"

$BackendWindow = Start-Process -FilePath 'powershell.exe' -WindowStyle Normal -PassThru `
    -ArgumentList '-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $BackendCommand `
    -WorkingDirectory $ProjectRoot

$BackendReady = $false
$StartupDeadline = [DateTime]::UtcNow.AddSeconds(60)
while ([DateTime]::UtcNow -lt $StartupDeadline) {
    if ($BackendWindow.HasExited) { throw 'The backend window was closed before startup completed.' }
    try {
        $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/openapi.json' -UseBasicParsing -TimeoutSec 2
        $BackendReady = $true
        break
    } catch {
        Start-Sleep -Milliseconds 300
    }
}
if (-not $BackendReady) { throw 'Backend startup timed out. Check the PaperReader - Backend window for errors.' }

Start-Process -FilePath 'powershell.exe' -WindowStyle Normal `
    -ArgumentList '-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $FrontendCommand `
    -WorkingDirectory $FrontendPath

Write-Host 'Opened backend window: http://127.0.0.1:8000'
Write-Host 'Opened frontend window: http://127.0.0.1:5173'
Write-Host 'Press Ctrl+C in each window to stop its service, then close the window.'
