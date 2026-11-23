$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
$backup = Join-Path $PSScriptRoot 'respaldo_pre_analisis_live_20261118_144107'

if (Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Cierre TraderAssistant (puerto 5174) antes de restaurar.'
}

$expected = @{
    'app.py' = 'A15D6C79944C873F9B1873D3912604320E682AF4C8A53EA4FBE0F0757BAAE3B5'
    'ui\live.html' = 'DA38C673F563BBABC8E52792207F9EEE5CBEF2BD1FBEFCE9490A86DAAF3FA0B7'
    'analysis_live.py' = 'D1FFBD23EC85FF2B41BAC7F5F5751F433A5BCB1D8031421E1B466829A486250A'
    'pruebas\probar_analysis_live.py' = '361C777FF433544DBC7D237C2BFC0C5546D139F2554707F1D1410AD096AF40CF'
    'pruebas\probar_analysis_ui.js' = '12100FFA2AF93B7A3C371EA98077827DEF9DC28B788BDF895470D2D1CF457B72'
    'pruebas\probar_analysis_process.py' = '19A8F593F2B6D6831745F76219ED99AC830E526635CE2F68F89A71B44B1A1082'
}

foreach ($relative in $expected.Keys) {
    $target = Join-Path $project $relative
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "No existe el archivo esperado: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    if ($actual -ne $expected[$relative]) {
        throw "Restauracion cancelada: $relative fue modificado despues de la integracion."
    }
}

Copy-Item -LiteralPath (Join-Path $backup 'app.py') -Destination (Join-Path $project 'app.py')
Copy-Item -LiteralPath (Join-Path $backup 'ui\live.html') -Destination (Join-Path $project 'ui\live.html')

foreach ($relative in @(
    'analysis_live.py',
    'pruebas\probar_analysis_live.py',
    'pruebas\probar_analysis_ui.js',
    'pruebas\probar_analysis_process.py'
)) {
    Remove-Item -LiteralPath (Join-Path $project $relative)
}

$restoredApp = (Get-FileHash -LiteralPath (Join-Path $project 'app.py') -Algorithm SHA256).Hash
$restoredUi = (Get-FileHash -LiteralPath (Join-Path $project 'ui\live.html') -Algorithm SHA256).Hash
if ($restoredApp -ne '7EC5304A6D07719E4D3FE44B1C900132A203F7F8D0C233F4FCD61351DF802FC0' -or
    $restoredUi -ne '5EC5B7B11A8275D4CBCAF173B6BFA31EEF2DAD2784962271F895AEA63EECCD04') {
    throw 'Los archivos restaurados no coinciden con el respaldo verificado.'
}

Write-Host 'Restauracion exacta completada. El informe y el respaldo se conservaron.'
