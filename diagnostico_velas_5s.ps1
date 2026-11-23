# Diagnostico read-only para Windows PowerShell 5.1.
# No lee credenciales, no cambia archivos, no conecta con IQ Option.
$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:5174/api/alpaca/live'
$observaciones = @()
Write-Host 'Recopilando durante 20 segundos: cotizaciones, trades y velas IEX...' -ForegroundColor Cyan
for ($i=1; $i -le 20; $i++) {
    try {
        $r = Invoke-RestMethod -Uri $url -TimeoutSec 5
        $b = $null
        if ($r.short_candles -and $r.short_candles.Count -gt 0) {
            $b = $r.short_candles[-1]
        }
        $q = $r.last_quote
        $t = $r.last_trade
        $observaciones += [pscustomobject]@{
            Muestra = $i
            HoraPC = (Get-Date).ToString('HH:mm:ss')
            Estado = [string]$r.status
            Trades = [long]$r.trade_count
            Quotes = [long]$r.quote_count
            Elegibles = [long]$r.eligible_count
            Vela5sInicioUnix = $(if ($b) {[long]$b.time} else {0})
            Cierre5s = $(if ($b) {[double]$b.close} else {0})
            MedioBidAsk = $(if ($q) {[double]$q.mid} else {0})
            UltimoTrade = $(if ($t) {[double]$t.price} else {0})
        }
    } catch {
        Write-Host ('La API local no respondió en muestra ' + $i + ': ' + $_.Exception.Message) -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 1
}
if ($observaciones.Count -lt 2) {throw 'Se necesitan al menos 2 muestras válidas. Ejecuta TraderAssistant primero.'}
$first = $observaciones[0]
$last = $observaciones[-1]
$diff = if ($last.Cierre5s -gt 0 -and $last.MedioBidAsk -gt 0) {
    [math]::Abs($last.Cierre5s - $last.MedioBidAsk)
} else {0}
$pct = if ($last.MedioBidAsk -gt 0) {100 * $diff / $last.MedioBidAsk} else {0}
Write-Host 'RESUMEN (sin credenciales):' -ForegroundColor Green
[pscustomobject]@{
    EstadoIEX = $last.Estado
    TradesNuevos = $last.Trades - $first.Trades
    CotizacionesNuevas = $last.Quotes - $first.Quotes
    ElegiblesNuevas = $last.Elegibles - $first.Elegibles
    CambioUltimaVela5s = ($last.Vela5sInicioUnix -ne $first.Vela5sInicioUnix)
    UltimoCierre5s = $last.Cierre5s
    UltimaCotizacionMedia = $last.MedioBidAsk
    DiferenciaUSD = [math]::Round($diff,6)
    DiferenciaPorcentaje = [math]::Round($pct,4)
} | Format-List
Write-Host 'Últimas 5 muestras:' -ForegroundColor Cyan
$observaciones | Select-Object -Last 5 | Format-Table -AutoSize
