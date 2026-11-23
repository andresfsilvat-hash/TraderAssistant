$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
$backup = Join-Path $PSScriptRoot 'respaldo_pre_correccion_sync_fase6_20261119_112652'

if (Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Cierre TraderAssistant antes de restaurar la lectura y el panel.'
}

$expected = @{
    'simulation_results.py' = '60A1B32D63305339EAF69FE889B216FE5A99A933D0D86095BCA5EE7FBD543909'
    'ui\live.html' = 'A30052A3DB5597BF830E186FA5988B19669CFC1BFD028B2153665577D62900A9'
    'pruebas\test_fase6_multihorizonte.py' = 'EB2E7C9CFB5162C720AD52D36EC2740C95F5F702EB5A880F241195F680DF612D'
    'pruebas\probar_analysis_ui.js' = '8CFF70F2D987E92BED2FD94E99DD786B550BAED4071F2CB27B0AAFAAD48DC7F9'
}

foreach ($relative in $expected.Keys) {
    $target = Join-Path $project $relative
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "No existe el archivo corregido esperado: $relative"
    }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expected[$relative]) {
        throw "Restauración cancelada: $relative cambió después de la corrección."
    }
}

foreach ($relative in $expected.Keys) {
    Copy-Item -LiteralPath (Join-Path $backup $relative) -Destination (Join-Path $project $relative)
}

Write-Host 'Lectura y panel restaurados al estado previo. Simulaciones e históricos no fueron modificados.'
