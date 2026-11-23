$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = Join-Path $PSScriptRoot 'respaldo_pre_validacion_1_2_5_10_20261119_124955'

$files = @(
    'decision_engine_experimental.py',
    'simulador_prospectivo_nvda_2min.py',
    'simulation_results.py',
    'ui\live.html',
    'pruebas\test_fase6_multihorizonte.py',
    'pruebas\probar_analysis_ui.js'
)

foreach ($relativePath in $files) {
    $source = Join-Path $backupRoot $relativePath
    $destination = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Falta el respaldo requerido: $source"
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$createdCodeFiles = @(
    'validar_prospectivo_multihorizonte.py',
    'pruebas\test_validacion_prospectiva_multihorizonte.py'
)
foreach ($relativePath in $createdCodeFiles) {
    $target = Join-Path $projectRoot $relativePath
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
    }
}

$expected = @{
    'decision_engine_experimental.py' = 'D6407B056BA78A5967CF56C2DE67635BCD87987E4208EE21E71C637AE61B6B74'
    'simulador_prospectivo_nvda_2min.py' = 'D018F1B07F24B654DEAC356996BD60725F393B9F7105991A9799FD194E1AC4C3'
    'simulation_results.py' = '60A1B32D63305339EAF69FE889B216FE5A99A933D0D86095BCA5EE7FBD543909'
    'ui\live.html' = 'A30052A3DB5597BF830E186FA5988B19669CFC1BFD028B2153665577D62900A9'
    'pruebas\test_fase6_multihorizonte.py' = 'EB2E7C9CFB5162C720AD52D36EC2740C95F5F702EB5A880F241195F680DF612D'
    'pruebas\probar_analysis_ui.js' = '8CFF70F2D987E92BED2FD94E99DD786B550BAED4071F2CB27B0AAFAAD48DC7F9'
}

foreach ($relativePath in $expected.Keys) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $projectRoot $relativePath)).Hash
    if ($actual -ne $expected[$relativePath]) {
        throw "Hash inesperado después de restaurar: $relativePath"
    }
}

Write-Output 'Restauración previa a validación 1/2/5/10 completada y verificada.'
