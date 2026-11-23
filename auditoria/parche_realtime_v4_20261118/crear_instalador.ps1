$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$base = Split-Path -Parent $MyInvocation.MyCommand.Path
function To-Base64([string]$Path) {
    return [Convert]::ToBase64String([IO.File]::ReadAllBytes($Path))
}

$backend64 = To-Base64 (Join-Path $base 'payload\alpaca_live.py')
$ui64 = To-Base64 (Join-Path $base 'payload\live.html')
$testPy64 = To-Base64 (Join-Path $base 'pruebas\probar_realtime_activo.py')
$testJs64 = To-Base64 (Join-Path $base 'pruebas\probar_ui_realtime_activa.js')
$rollback64 = To-Base64 (Join-Path $base 'Revertir_TraderAssistant_REALTIME_v4.ps1')

$template = @'
param([string]$ProjectPath = 'C:\Proyectos\TraderAssistant')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ProjectPath = [IO.Path]::GetFullPath($ProjectPath)
if (-not (Test-Path -LiteralPath (Join-Path $ProjectPath 'app.py') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $ProjectPath 'main.py') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $ProjectPath 'ui\vendor\lightweight-charts.js') -PathType Leaf)) {
    throw "No es un proyecto TraderAssistant valido: $ProjectPath"
}
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $listener = Get-NetTCPConnection -LocalPort 5174 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Cierre TraderAssistant antes de instalar (puerto 5174 ocupado).' }
}

$files = @(
    @{ relative='alpaca_live.py'; expected='10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127'; installed='__BACKEND_SHA__'; data='__BACKEND64__' },
    @{ relative='ui\live.html'; expected='CB5A81D657FB0D8E6BC2AFE27CEA8BCFA798704E06966A304EE5C42A00D1C29A'; installed='__UI_SHA__'; data='__UI64__' },
    @{ relative='pruebas\probar_realtime_activo.py'; expected=$null; installed='__TESTPY_SHA__'; data='__TESTPY64__' },
    @{ relative='pruebas\probar_ui_realtime_activa.js'; expected=$null; installed='__TESTJS_SHA__'; data='__TESTJS64__' }
)

$backendCurrent = (Get-FileHash -LiteralPath (Join-Path $ProjectPath 'alpaca_live.py') -Algorithm SHA256).Hash
$uiCurrent = (Get-FileHash -LiteralPath (Join-Path $ProjectPath 'ui\live.html') -Algorithm SHA256).Hash
if ($backendCurrent -eq $files[0].installed -and $uiCurrent -eq $files[1].installed) {
    Write-Host 'La estabilizacion REALTIME ya esta instalada.' -ForegroundColor Green
    exit 0
}
if ($backendCurrent -ne $files[0].expected) {
    throw 'alpaca_live.py cambio desde la auditoria. Instalacion cancelada para no sobrescribir cambios desconocidos.'
}
if ($uiCurrent -ne $files[1].expected) {
    throw 'ui\live.html cambio desde la auditoria. Instalacion cancelada para no sobrescribir cambios desconocidos.'
}

$protectedPaths = @((Join-Path $ProjectPath 'app.py'), (Join-Path $ProjectPath 'main.py'), (Join-Path $ProjectPath 'config.json'))
$protectedPaths += @(Get-ChildItem -LiteralPath (Join-Path $ProjectPath 'screener') -Recurse -File | ForEach-Object FullName)
$protected = @{}
foreach ($path in $protectedPaths) {
    if (Test-Path -LiteralPath $path -PathType Leaf) { $protected[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = Join-Path $ProjectPath (Join-Path 'auditoria' ("respaldo_instalacion_realtime_" + $stamp))
$originalRoot = Join-Path $backup 'original'
$payloadRoot = Join-Path $backup 'payload_verificado'
New-Item -ItemType Directory -Path $originalRoot,$payloadRoot -Force | Out-Null
$manifestFiles = @()
$installedTargets = @()

try {
    foreach ($entry in $files) {
        $target = Join-Path $ProjectPath $entry.relative
        $original = Join-Path $originalRoot $entry.relative
        $decoded = Join-Path $payloadRoot $entry.relative
        $originalExisted = Test-Path -LiteralPath $target -PathType Leaf
        if ($originalExisted) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $original) -Force | Out-Null
            Copy-Item -LiteralPath $target -Destination $original -Force
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $decoded) -Force | Out-Null
        [IO.File]::WriteAllBytes($decoded, [Convert]::FromBase64String([string]$entry.data))
        $decodedHash = (Get-FileHash -LiteralPath $decoded -Algorithm SHA256).Hash
        if ($decodedHash -ne [string]$entry.installed) { throw "Payload corrupto: $($entry.relative)" }
        $manifestFiles += [ordered]@{ relative=$entry.relative; original_existed=$originalExisted;
            original_sha256=$(if($originalExisted){(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash}else{$null});
            installed_sha256=$entry.installed }
    }

    foreach ($entry in $files) {
        $target = Join-Path $ProjectPath $entry.relative
        $decoded = Join-Path $payloadRoot $entry.relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $decoded -Destination $target -Force
        $installedTargets += $target
    }

    $manifest = [ordered]@{ project_path=$ProjectPath; installed_at=(Get-Date).ToString('o'); version='4.0.0'; files=$manifestFiles }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backup 'manifest.json') -Encoding UTF8
    [IO.File]::WriteAllBytes((Join-Path $backup 'Revertir_TraderAssistant_REALTIME_v4.ps1'),
        [Convert]::FromBase64String('__ROLLBACK64__'))

    $python = Join-Path $ProjectPath 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'No se encontro el Python del entorno virtual.' }
    Push-Location $ProjectPath
    try {
        & $python -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'),f,'exec') for f in ('alpaca_live.py','app.py','main.py')]; print('Sintaxis Python OK')"
        if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion de sintaxis Python.' }
        & $python (Join-Path $ProjectPath 'pruebas\probar_realtime_activo.py')
        if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas de regresion REALTIME.' }
        if (Get-Command node -ErrorAction SilentlyContinue) {
            & node (Join-Path $ProjectPath 'pruebas\probar_ui_realtime_activa.js')
            if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas de interfaz REALTIME.' }
        } else {
            Write-Warning 'Node.js no esta disponible; se omite la prueba UI opcional.'
        }
    } finally {
        Pop-Location
    }
    foreach ($path in $protected.Keys) {
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $protected[$path]) {
            throw "Un archivo protegido cambio durante la instalacion: $path"
        }
    }
} catch {
    foreach ($entry in $manifestFiles) {
        $target = Join-Path $ProjectPath ([string]$entry.relative)
        $original = Join-Path $originalRoot ([string]$entry.relative)
        if ([bool]$entry.original_existed) {
            Copy-Item -LiteralPath $original -Destination $target -Force
        } elseif (Test-Path -LiteralPath $target -PathType Leaf) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    throw "Instalacion cancelada y archivos restaurados. Causa: $($_.Exception.Message)"
}

Write-Host ''
Write-Host 'TraderAssistant REALTIME v4.0.0 estabilizado correctamente.' -ForegroundColor Green
Write-Host "Respaldo y reversor: $backup"
Write-Host ("Para iniciar: `"{0}`" `"{1}`"" -f (Join-Path $ProjectPath 'venv\Scripts\python.exe'), (Join-Path $ProjectPath 'main.py'))
'@

$replacements = [ordered]@{
    '__BACKEND64__'=$backend64; '__UI64__'=$ui64; '__TESTPY64__'=$testPy64; '__TESTJS64__'=$testJs64;
    '__ROLLBACK64__'=$rollback64;
    '__BACKEND_SHA__'=(Get-FileHash (Join-Path $base 'payload\alpaca_live.py') -Algorithm SHA256).Hash;
    '__UI_SHA__'=(Get-FileHash (Join-Path $base 'payload\live.html') -Algorithm SHA256).Hash;
    '__TESTPY_SHA__'=(Get-FileHash (Join-Path $base 'pruebas\probar_realtime_activo.py') -Algorithm SHA256).Hash;
    '__TESTJS_SHA__'=(Get-FileHash (Join-Path $base 'pruebas\probar_ui_realtime_activa.js') -Algorithm SHA256).Hash
}
foreach ($key in $replacements.Keys) { $template = $template.Replace($key, [string]$replacements[$key]) }
$output = Join-Path $base 'Instalar_TraderAssistant_REALTIME_v4.ps1'
[IO.File]::WriteAllText($output, $template, (New-Object Text.UTF8Encoding($false)))
Write-Host $output
