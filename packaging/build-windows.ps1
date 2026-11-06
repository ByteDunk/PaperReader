param(
    [switch]$SkipBackend,
    [switch]$SkipDesktop
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $ProjectRoot
$BackendPath = Join-Path $ProjectRoot 'backend'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv was not found. Please install uv first.' }
& uv sync --project $BackendPath --locked --no-dev --group build
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency synchronization failed.' }

# Prefer a project-local toolchain when available; normal rustup installations also work.
$LocalCargo = Join-Path $ProjectRoot '.build\cargo'
if (Test-Path -LiteralPath (Join-Path $LocalCargo 'bin\cargo.exe')) {
    $env:CARGO_HOME = $LocalCargo
    $env:RUSTUP_HOME = Join-Path $ProjectRoot '.build\rustup'
    $env:PATH = (Join-Path $LocalCargo 'bin') + ';' + $env:PATH
}
$PortableMsvc = Join-Path $ProjectRoot '.build\msvc'
if (Test-Path -LiteralPath (Join-Path $PortableMsvc 'setup_x64.bat')) {
    $Compiler = Get-ChildItem -LiteralPath (Join-Path $PortableMsvc 'VC\Tools\MSVC') -Directory | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    $SdkRoot = Join-Path $PortableMsvc 'Windows Kits\10'
    $Sdk = Get-ChildItem -LiteralPath (Join-Path $SdkRoot 'Lib') -Directory | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    $env:VCToolsInstallDir = $Compiler.FullName + '\'
    $env:VCToolsVersion = $Compiler.Name
    $env:WindowsSdkDir = $SdkRoot + '\'
    $env:WindowsSDKVersion = $Sdk.Name + '\'
    $env:VSCMD_ARG_HOST_ARCH = 'x64'
    $env:VSCMD_ARG_TGT_ARCH = 'x64'
    $env:PATH = (Join-Path $Compiler.FullName 'bin\Hostx64\x64') + ';' + (Join-Path $SdkRoot "bin\$($Sdk.Name)\x64") + ';' + $env:PATH
    $env:INCLUDE = (Join-Path $Compiler.FullName 'include') + ';' + ((@('ucrt','shared','um','winrt','cppwinrt') | ForEach-Object { Join-Path $SdkRoot "Include\$($Sdk.Name)\$_" }) -join ';')
    $env:LIB = (Join-Path $Compiler.FullName 'lib\x64') + ';' + (Join-Path $Sdk.FullName 'ucrt\x64') + ';' + (Join-Path $Sdk.FullName 'um\x64')
    $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER = Join-Path $Compiler.FullName 'bin\Hostx64\x64\link.exe'
}
$env:CARGO_TARGET_DIR = Join-Path $ProjectRoot '.build\tauri'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path (Join-Path $ProjectRoot '.build') -Force | Out-Null

if (-not $SkipBackend) {
    & uv run --project $BackendPath --locked --no-sync python -m PyInstaller --noconfirm --distpath .build\backend-dist --workpath .build\pyinstaller packaging\backend.spec
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
}
if (-not $SkipDesktop) {
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw 'Install the Rust MSVC toolchain before building.' }
    Push-Location -LiteralPath (Join-Path $ProjectRoot 'frontend')
    try {
        & npm.cmd run tauri -- build --no-bundle --target x86_64-pc-windows-msvc --features custom-protocol -- --locked
        if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed.' }
    } finally { Pop-Location }
}
& uv run --project $BackendPath --locked --no-sync python packaging\assemble.py
if ($LASTEXITCODE -ne 0) { throw 'Portable package assembly failed.' }
