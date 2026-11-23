$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$backupRoot = Join-Path $PSScriptRoot 'respaldo_pre_objetivo_principal_20261121_070259'

$restoreFiles = @(
    'analysis_live.py',
    'decision_engine_experimental.py',
    'simulador_prospectivo_nvda_2min.py',
    'simulation_results.py',
    'validar_prospectivo_multihorizonte.py',
    'ui\live.html',
    'pruebas\probar_analysis_live.py',
    'pruebas\probar_analysis_ui.js',
    'pruebas\test_fase6_multihorizonte.py',
    'pruebas\test_simulador_prospectivo_nvda_2min.py',
    'pruebas\test_validacion_prospectiva_multihorizonte.py',
    'auditoria\plantilla_precios_iq_option.csv'
)

foreach ($relativePath in $restoreFiles) {
    $source = Join-Path $backupRoot $relativePath
    $destination = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Falta respaldo requerido: $source"
    }
    Copy-Item -LiteralPath $source -Destination $destination -Force
}

$createdCodeFiles = @(
    'multitimeframe_context.py',
    'evaluar_motor_multihorizonte.py',
    'pruebas\test_objetivo_principal.py'
)
foreach ($relativePath in $createdCodeFiles) {
    $target = Join-Path $projectRoot $relativePath
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
    }
}

$manifest = Get-Content -LiteralPath (Join-Path $backupRoot 'hashes_pre.json') -Raw | ConvertFrom-Json
foreach ($property in $manifest.files.PSObject.Properties) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $projectRoot $property.Name)).Hash
    if ($actual -ne [string]$property.Value) {
        throw "Hash inesperado después de restaurar: $($property.Name)"
    }
}
$templatePath = Join-Path $projectRoot 'auditoria\plantilla_precios_iq_option.csv'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $templatePath).Hash -ne '88C7D72A7A372F84EC5446831465207879EDAF789DC15B0006666C502E6B65EC') {
    throw 'Hash inesperado después de restaurar la plantilla IQ Option.'
}

Write-Output 'Restauración previa al objetivo principal completada y verificada.'
