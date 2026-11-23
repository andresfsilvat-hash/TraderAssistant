
'use strict';
const $ = (id) => document.getElementById(id);
const TZ = 'America/Guayaquil';
const fullTime = new Intl.DateTimeFormat('es-EC', {timeZone:TZ,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const hours = new Intl.DateTimeFormat('es-EC', {timeZone:TZ,hour:'2-digit',minute:'2-digit',hour12:false});
const hoursSeconds = new Intl.DateTimeFormat('es-EC', {timeZone:TZ,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
const days = new Intl.DateTimeFormat('es-EC', {timeZone:TZ,day:'2-digit',month:'short'});
const fromUnix = (ts) => new Date(Number(ts)*1000);
function timeLabel(iso) {if(!iso)return '—';const date=new Date(iso);return Number.isFinite(date.getTime())?fullTime.format(date)+' EC':'—';}
function timeAge(iso) {const n=Date.parse(iso||'');return Number.isFinite(n)?Math.max(0,Math.floor((Date.now()-n)/1000)):null;}
function textAge(s) {return s===null?'—':s+' s';}
function volumePoint(b) {return {time:b.time,value:b.volume,color:b.close>=b.open?'#23c48344':'#f4525a44'};}

const chartEl = $('chart');
if(typeof LightweightCharts==='undefined') {
  $('empty').textContent='Error: no se pudo cargar lightweight-charts.js';
  throw new Error('No se cargo la libreria local de graficos');
}
const chart = LightweightCharts.createChart(chartEl, {
  width:chartEl.clientWidth,height:Math.max(390,chartEl.clientHeight-1),
  layout:{background:{color:'#0e1119'},textColor:'#92a3bb'},
  grid:{vertLines:{color:'#21283a'},horzLines:{color:'#21283a'}},
  crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
  rightPriceScale:{borderColor:'#34435c'},
  localization:{locale:'es-EC',timeFormatter:(t)=>fullTime.format(fromUnix(t))+' EC'},
  timeScale:{borderColor:'#34435c',timeVisible:true,secondsVisible:false,rightOffset:7,
    tickMarkFormatter:(t,k)=>k<=2?days.format(fromUnix(t)):hours.format(fromUnix(t))}
});
const candle = chart.addCandlestickSeries({upColor:'#23c483',downColor:'#f4525a',borderUpColor:'#23c483',borderDownColor:'#f4525a',wickUpColor:'#23c483',wickDownColor:'#f4525a'});
const volume = chart.addHistogramSeries({color:'#5475ae66',priceFormat:{type:'volume'},priceScaleId:'volume'});
chart.priceScale('volume').applyOptions({scaleMargins:{top:.82,bottom:0}});

let tf='1m';
let lastPayload=null;
let lastSignature='';
let lastTime=null;
let count=0;
let revision=null;
let firstDraw=true;
let following=true;
let lastTradeStamp=null;
let lastRenderedTradeStamp=null;
let lastFetchedAt=0;
let fetchBusy=false;
let fetchQueued=false;
let fetchTimer=null;
let sseOk=false;

function seriesFor(data) {
  if(tf==='5s')return data.short_candles||[];
  if(tf==='1m')return data.candles||[];
  const combined=[];
  for(const b of data.candles||[]) {
    const bucket=Math.floor(b.time/300)*300;
    const tail=combined[combined.length-1];
    if(tail&&tail.time===bucket) {
      tail.high=Math.max(tail.high,b.high);
      tail.low=Math.min(tail.low,b.low);
      tail.close=b.close;
      tail.volume+=b.volume;
      tail.provisional=tail.provisional||b.provisional;
    }else combined.push({...b,time:bucket});
  }
  return combined;
}
function tfSeconds() {return tf==='5s'?5:tf==='5m'?300:60;}
function focusLatest(n=count) {
  if(!n)return;
  const shown=tf==='5s'?75:65;
  chart.timeScale().setVisibleLogicalRange({from:Math.max(-0.5,n-shown),to:n+5});
}
function updateTfButtons() {
  for(const t of ['5s','1m','5m'])$('tf'+t).classList.toggle('active',tf===t);
  chart.applyOptions({timeScale:{secondsVisible:tf==='5s',timeVisible:true,
    tickMarkFormatter:(t,k)=>k<=2?days.format(fromUnix(t)):(tf==='5s'?hoursSeconds:hours).format(fromUnix(t))}});
}
function changeTf(value) {
  if(tf===value)return;
  tf=value;lastSignature='';lastTime=null;count=0;revision=null;firstDraw=true;
  candle.setData([]);volume.setData([]);
  updateTfButtons();if(lastPayload)drawData(lastPayload);
}
$('tf5s').addEventListener('click',()=>changeTf('5s'));
$('tf1m').addEventListener('click',()=>changeTf('1m'));
$('tf5m').addEventListener('click',()=>changeTf('5m'));
$('follow').addEventListener('click',()=>{
  following=!following;$('follow').classList.toggle('active',following);
  if(following)focusLatest();
});

function drawData(data) {
  const bars=seriesFor(data), last=bars[bars.length-1];
  const sig=last?[bars.length,last.time,last.open,last.high,last.low,last.close,last.volume,Number(!!last.provisional)].join(':'):'empty';
  const changedRev=revision!==null&&revision!==data.series_revision;
  const hadData=count>0;
  if(sig!==lastSignature||changedRev) {
    const needsReset=firstDraw||changedRev||!last||lastTime===null||bars.length<count||bars.length>count+1||last.time<lastTime;
    if(needsReset) {
      candle.setData(bars.map(b=>({time:b.time,open:b.open,high:b.high,low:b.low,close:b.close})));
      volume.setData(bars.map(volumePoint));
      if(following&&bars.length&&(firstDraw||!hadData||changedRev))focusLatest(bars.length);
    }else if(last) {
      candle.update({time:last.time,open:last.open,high:last.high,low:last.low,close:last.close});
      volume.update(volumePoint(last));
      if(following&&last.time>lastTime)chart.timeScale().scrollToRealTime();
    }
    firstDraw=false;
    lastSignature=sig;
    lastTime=last?last.time:null;
    count=bars.length;
  }
  revision=data.series_revision;
  $('count').textContent=bars.length+' velas · '+tf;
  $('empty').style.display=bars.length?'none':'flex';
  $('empty').textContent=data.status==='error'?'Alpaca: error de conexion':tf==='5s'?'Esperando operaciones elegibles en vivo…':'Esperando historial o nueva vela IEX…';
  $('bar-quality').textContent=tf==='5s'?'5 s indicativas':last?.provisional?'Última vela: provisional':'Última vela: oficial IEX';
  drawClock(data);
}

function drawClock(data) {
  if(!data)return;
  const now=Date.now();
  const recentTrade=data.last_trade;
  const last=data.last_trade||null;
  const lastAt=last?Date.parse(last.timestamp):NaN;
  const arrivedAt=data.last_received_at?Date.parse(data.last_received_at):NaN;
  const arrivedAge=timeAge(data.last_received_at);
  const tradeAge=Number.isFinite(lastAt)?Math.max(0,Math.floor((now-lastAt)/1000)):null;
  const packetAge=timeAge(data.last_feed_message_at);
  $('version').textContent='v'+(data.version_info||'4');
  $('price').textContent=last?'$'+Number(last.price).toFixed(3):'—';
  if(last&&last.timestamp!==lastTradeStamp) {
    if(lastTradeStamp!==null) {
      $('price').classList.remove('flash');void $('price').offsetWidth;$('price').classList.add('flash');
    }
    lastTradeStamp=last.timestamp;
  }
  $('trade-time').textContent=last?'Operación: '+timeLabel(last.timestamp):'Esperando la primera operación IEX';
  $('age').textContent=textAge(arrivedAge);
  $('received-time').textContent=data.last_received_at?'Recibido: '+timeLabel(data.last_received_at):'Sin operaciones recibidas';
  $('lag').textContent=Number.isFinite(data.last_lag_ms)&&data.last_lag_ms>=0?
    'Bolsa → servidor: '+(data.last_lag_ms/1000).toFixed(2)+' s (aprox.)':
    'Bolsa → servidor: sin medición fiable';
  const next=data.candles&&data.candles.length?data.candles[data.candles.length-1]:null;
  const bars=seriesFor(data),bar=bars[bars.length-1];
  const ageMs=Date.now()-lastFetchedAt;
  $('visual-age').textContent='Pantalla: '+(lastFetchedAt?Math.round(ageMs/1000)+' s desde sincronización':'esperando primera sincronización');
  const channelState=data.status==='conectado';
  const healthy=channelState&&packetAge!==null&&packetAge<20;
  $('dot').className='dot '+(channelState?'good':data.status==='error'?'bad':'');
  $('connection').textContent=data.status==='error'?'IEX: error':data.status==='reconectando'?'IEX: reconectando…':
    channelState?(healthy?'IEX: conectado':'IEX: conectado, sin mensajes recientes'):
    data.status==='conectando'?'IEX: conectando…':(data.status||'Esperando IEX');
  $('trade-state').textContent=channelState?(arrivedAge!==null&&arrivedAge<10?'Recibiendo operaciones':'Sin operaciones IEX recientes (no es un bloqueo)'):
    (data.status||'Esperando conexion');
  $('trade-count').textContent='Trades: '+(data.trade_count||0)+' · elegibles: '+(data.eligible_count||0)+' · excluidos: '+(data.excluded_count||0);
  $('error').textContent=data.error||data.history_error||'';
  if(bar) {
    const duration=tfSeconds();
    const remainder=bar.provisional?Math.max(0,duration-(Math.floor(now/1000)-bar.time)):0;
    $('progress').style.width=bar.provisional?Math.max(0,Math.min(100,(duration-remainder)/duration*100))+'%':'0%';
    $('bar-status').textContent=bar.provisional?'EN FORMACIÓN':'OFICIAL';
    $('bar-start').textContent='Inicio: '+timeLabel(new Date(bar.time*1000).toISOString());
    const variation=bar.open?100*(bar.close-bar.open)/bar.open:0;
    const move=$('movement');move.className='v '+(variation>0?'up':variation<0?'down':'flat');
    move.textContent=(variation>0?'▲ ':variation<0?'▼ ':'= ')+Math.abs(variation).toFixed(3)+'%';
    $('movement-detail').textContent=(bar.provisional?'Estimación provisional':'Vela oficial')+' · no es predicción';
  }else {
    $('bar-status').textContent='—';$('bar-start').textContent='Sin velas';
    $('movement').textContent='—';$('movement').className='v flat';
    $('movement-detail').textContent='Sin vela para medir variación';
    $('progress').style.width='0%';
  }
}

async function fetchSnapshot() {
  if(fetchBusy){fetchQueued=true;return;}
  fetchBusy=true;
  try {
    const response=await fetch('/api/alpaca/live',{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const data=await response.json();
    lastFetchedAt=Date.now();
    if(data.last_received_at&&data.last_received_at!==lastRenderedTradeStamp) {
      lastRenderedTradeStamp=data.last_received_at;
      const ms=Date.now()-Date.parse(data.last_received_at);
      $('paint-delay').textContent=ms>=0?'Servidor → pantalla: '+ms+' ms (aprox.)':'Reloj del PC no sincronizado';
    }
    lastPayload=data;
    drawData(data);
  }catch(e) {
    $('delivery').textContent='Canal local: reintentando';
    $('error').textContent='No se pudo leer la API local ('+String(e.message||'Error')+').';
  }finally{
    fetchBusy=false;
    if(fetchQueued){fetchQueued=false;scheduleFetch();}
  }
}
function scheduleFetch(){
  if(fetchTimer!==null)return;
  fetchTimer=setTimeout(()=>{fetchTimer=null;fetchSnapshot();},100);
}
// SSE notifica cambios; petición local corta para consultar el estado.
// Si falla SSE, la UI utiliza una comprobación de respaldo cada 3 segundos.
if(typeof EventSource!=='undefined') {
  const source=new EventSource('/api/alpaca/events');
  source.addEventListener('update',()=>{sseOk=true;$('delivery').textContent='Canal: streaming';scheduleFetch();});
  source.onopen=()=>{sseOk=true;$('delivery').textContent='Canal: SSE conectado';};
  source.onerror=()=>{sseOk=false;$('delivery').textContent='Canal: SSE reconectando; respaldo activo';};
}else $('delivery').textContent='Canal: respaldo periódico';
fetchSnapshot();
setInterval(()=>{
  if(lastPayload)drawClock(lastPayload); // reloj activo aun sin trades, no inventar OHLC
  if(Date.now()-lastFetchedAt>3000||!sseOk)scheduleFetch();
},1000);
function resizeChart(){chart.resize(chartEl.clientWidth,Math.max(390,chartEl.clientHeight-1));}
if(typeof ResizeObserver!=='undefined')new ResizeObserver(resizeChart).observe(chartEl);
else window.addEventListener('resize',resizeChart);
