param(
    [switch]$SkipBackend,
    [switch]$SkipDesktop
)

$ErrorActionPreference = 'Stop'

# Run the complete Windows build: backend, Vue/Tauri, and portable package.
# Optional switches reuse the corresponding existing build outputs.
& (Join-Path $PSScriptRoot 'packaging\build-windows.ps1') @PSBoundParameters
