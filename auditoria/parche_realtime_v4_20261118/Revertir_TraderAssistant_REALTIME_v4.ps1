param([switch]$Force)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$manifestPath = Join-Path $PSScriptRoot 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw 'No se encontro manifest.json junto al reversor.'
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$project = [IO.Path]::GetFullPath([string]$manifest.project_path)
if (-not (Test-Path -LiteralPath (Join-Path $project 'app.py') -PathType Leaf)) {
    throw "Proyecto no valido: $project"
}
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $listener = Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Cierre TraderAssistant antes de revertir (puerto 5174 ocupado).' }
}

foreach ($entry in $manifest.files) {
    $target = Join-Path $project ([string]$entry.relative)
    if ((Test-Path -LiteralPath $target -PathType Leaf) -and -not $Force) {
        $current = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
        if ($current -ne [string]$entry.installed_sha256) {
            throw "El archivo cambio despues de instalar y no se sobrescribira: $target. Use -Force solo tras revisar sus cambios."
        }
    }
}

foreach ($entry in $manifest.files) {
    $relative = [string]$entry.relative
    $target = Join-Path $project $relative
    $backup = Join-Path (Join-Path $PSScriptRoot 'original') $relative
    if ([bool]$entry.original_existed) {
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item -LiteralPath $backup -Destination $target -Force
    } elseif (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
    }
}

Write-Host 'Reversion completada. Se restauraron los archivos originales del respaldo:' -ForegroundColor Green
Write-Host $PSScriptRoot
