$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
$backup = Join-Path $PSScriptRoot 'respaldo_pre_fase6_multihorizonte_20261119_101906'

if (Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Cierre TraderAssistant antes de restaurar.'
}

$expected = @{
    'app.py' = '820FFBCC43B53C1AEAFBD1BA920BC1203B4D39BF4CB1A6D3AE855A50FD7ED51A'
    'decision_engine_experimental.py' = 'D6407B056BA78A5967CF56C2DE67635BCD87987E4208EE21E71C637AE61B6B74'
    'simulation_results.py' = '0E10208063B6E8203DB8471708864B99E13D7086C4902A3A70FB1D5F5AD42D07'
    'simulador_prospectivo_nvda_2min.py' = 'D018F1B07F24B654DEAC356996BD60725F393B9F7105991A9799FD194E1AC4C3'
    'ui\live.html' = '9EC6023EEB7F14A35BADC49F85081968A759C0B40A6B2F994C3E70DC4DD93E55'
    'pruebas\test_simulador_prospectivo_nvda_2min.py' = 'F53D6A8AAA10F9D8CD65562369E1FD58CA5326BB845E40AFEA2A6AF8648E0B7D'
    'pruebas\test_fase6_multihorizonte.py' = '3DB70243FEE98126E7EAE2C2E2B51523687C1F5D6B77DCE647B2D73292486D90'
    'pruebas\probar_analysis_ui.js' = 'B5F5E4A7066941AB2D76670F96AD35283AFAB2FC436FE985D39DBE2F53A27CCC'
}

foreach ($relative in $expected.Keys) {
    $target = Join-Path $project $relative
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "No existe el archivo integrado esperado: $relative"
    }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expected[$relative]) {
        throw "Restauración cancelada: $relative cambió después de Fase 6."
    }
}

foreach ($relative in @(
    'app.py',
    'simulador_prospectivo_nvda_2min.py',
    'ui\live.html',
    'pruebas\test_simulador_prospectivo_nvda_2min.py',
    'pruebas\probar_analysis_ui.js'
)) {
    Copy-Item -LiteralPath (Join-Path $backup $relative) -Destination (Join-Path $project $relative)
}

foreach ($relative in @(
    'decision_engine_experimental.py',
    'simulation_results.py',
    'pruebas\test_fase6_multihorizonte.py'
)) {
    Remove-Item -LiteralPath (Join-Path $project $relative)
}

Write-Host 'Restauración pre-Fase 6 completada. Históricos, respaldo e informes se conservaron.'
