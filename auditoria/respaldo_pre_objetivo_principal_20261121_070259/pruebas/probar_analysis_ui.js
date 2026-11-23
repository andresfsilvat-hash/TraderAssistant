'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const ROOT=path.resolve(__dirname,'..');
const uiPath=path.join(ROOT,'ui','live.html');
const html=fs.readFileSync(uiPath,'utf8');
assert(html.includes('<option value="60">1 min</option>'),'Debe existir el horizonte seleccionable de 1 minuto');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const source=scripts[scripts.length-1][1];
const elements=new Map();
const get=id=>{
  if(!elements.has(id))elements.set(id,{id,clientWidth:1100,clientHeight:700,offsetWidth:400,
    style:{},textContent:'',className:'',value:'NVDA',disabled:false,attributes:{},
    classList:{add(){},remove(){},toggle(){}},setAttribute(k,v){this.attributes[k]=v;},
    addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn;}});
  return elements.get(id);
};
const seriesState=[];
const makeSeries=()=>{const state={data:[],options:[]};seriesState.push(state);return {
  setData(data){state.data=data;},update(item){const last=state.data[state.data.length-1];if(last&&last.time===item.time)state.data[state.data.length-1]=item;else state.data.push(item);},
  applyOptions(options){state.options.push(options);}};};
const chart={addCandlestickSeries:makeSeries,addLineSeries:makeSeries,addHistogramSeries:makeSeries,
  priceScale(){return {applyOptions(){}};},applyOptions(){},resize(){},
  timeScale(){return {setVisibleLogicalRange(){},scrollToRealTime(){}};}};
let eventSource;
class FakeEvents{constructor(url){assert.equal(url,'/api/alpaca/events');eventSource=this;}addEventListener(t,f){this.listeners??={};this.listeners[t]=f;}}
class FakeResize{observe(){}}
const storage={};
const localStorage={getItem:k=>storage[k]??null,setItem:(k,v)=>{storage[k]=v;}};
const base=1795008600;
const makeCandles=count=>Array.from({length:count},(_,i)=>({time:base+i*60,open:100+i*.01,high:100.3+i*.01,
  low:99.8+i*.01,close:100.1+i*.01,volume:1000+i,provisional:false}));
let live={status:'conectado',symbol:'NVDA',symbol_name:'NVIDIA',version_info:'4.0.0',build:'test',series_revision:0,
  history_source:'alpaca',candles:makeCandles(60),short_candles:[],quote_points:[],quotes_subscribed:true,
  market_clock:{source:'alpaca',is_open:true,checked_at:new Date().toISOString(),next_close:new Date(Date.now()+3600000).toISOString()},
  trade_count:1,quote_count:1,eligible_count:1,last_feed_message_at:new Date().toISOString(),
  last_trade:{price:100.7,timestamp:new Date().toISOString()},last_received_at:new Date().toISOString(),last_lag_ms:20,
  last_quote:{bid:100.6,ask:100.8,mid:100.7,timestamp:new Date().toISOString()},last_quote_received_at:new Date().toISOString(),last_quote_lag_ms:20};
const analysisFor=(bias,revision)=>({symbol:'NVDA',status:'ready',decision:'ESPERAR',bias,feed_revision:revision,
  reason:bias==='Alcista'?'Evidencia alcista: Hammer (1m). Interpretación técnica; no es señal de entrada.':'Sin condición activa.',
  values:{rsi_14:55.2,macd_histogram:.0123,bollinger_lower:99.1,bollinger_upper:102.2},
  patterns:bias==='Alcista'?['Hammer (1m)']:[],source:'alpaca',stale:false,
  last_candle_time:new Date(live.candles[live.candles.length-1].time*1000).toISOString(),row_count:live.candles.length,required_rows:40,
  service:{worker_busy:false}});
let analysis=analysisFor('Alcista',0),analysisFetches=0,liveFetches=0;
get('simulation-horizon').value='120';
let simulationFetches=0;
let simulation={symbol:'NVDA',selected_horizon_seconds:120,simulator_status:'ACTIVO',
  active_rules_version:'experimental-confluence-v1',statistics_by_rules_version:{
    'experimental-confluence-v1':{generated:1,entries:1,wins:0,losses:0,ties:0,not_evaluable:0,active:1}},
  latest:{id:'test',symbol:'NVDA',horizon_seconds:120,hypothesis:'SUBE',status:'ACTIVA',
    detected_at:new Date().toISOString(),entry_at:new Date().toISOString(),entry_price_iex:100.7,
    expiry_at:new Date(Date.now()+120000).toISOString(),result:null,is_current:true}};
const context={document:{getElementById:get,title:''},window:{addEventListener(){}},localStorage,
  LightweightCharts:{createChart:()=>chart,CrosshairMode:{Normal:0}},EventSource:FakeEvents,ResizeObserver:FakeResize,
  Intl,Date,Math,Number,Array,Object,String,Error,Map,JSON,
  setTimeout,clearTimeout,setInterval:()=>{},
  fetch:async(url,options)=>{
    if(url==='/api/analysis/live'){analysisFetches++;return {ok:true,json:async()=>analysis};}
    if(url.startsWith('/api/simulation/live?horizon=')){simulationFetches++;return {ok:true,json:async()=>simulation};}
    if(url==='/api/alpaca/symbol'&&options?.method==='POST')return {ok:true,json:async()=>({symbol:'AAPL',status:'ok'})};
    if(url==='/api/alpaca/live'){liveFetches++;return {ok:true,json:async()=>live};}
    throw new Error('Unexpected URL '+url);
  }};

(async()=>{
  vm.runInNewContext(source,context,{timeout:5000,filename:uiPath});
  await new Promise(r=>setTimeout(r,80));
  assert.equal(get('decision-bias').textContent,'Alcista');
  assert(get('decision-indicators').textContent.includes('RSI 55.2'));
  assert(get('decision-indicators').textContent.includes('Hammer'));
  assert(get('decision-reason').textContent.includes('ESPERAR'));
  assert(get('decision-analyzed-candle').textContent.includes('Alpaca'));
  assert.equal(get('simulation-hypothesis').textContent,'SUBE');
  assert(get('simulation-status').textContent.includes('ACTIVA'));
  assert(get('simulation-entry').textContent.includes('IEX 100.7'));
  get('simulation-horizon').value='300';
  simulation={symbol:'NVDA',selected_horizon_seconds:300,simulator_status:'ACTIVO',
    active_rules_version:'experimental-confluence-v1',statistics_by_rules_version:{
      'experimental-confluence-v1':{generated:2,entries:1,wins:0,losses:0,ties:0,not_evaluable:1,active:0}},
    active_simulation_status:'SIN_SIMULACION_ACTIVA',latest:null};
  get('simulation-horizon').listeners.change();
  await new Promise(r=>setTimeout(r,30));
  assert.equal(get('simulation-hypothesis').textContent,'ESPERAR');
  assert.equal(get('simulation-result').textContent,'SIN SIMULACIÓN ACTIVA');
  assert(get('simulation-status').textContent.includes('SIN SIMULACIÓN ACTIVA'));
  assert(get('simulation-stats').textContent.includes('N 2'));
  assert(seriesState[0].data.length===60,'El gráfico principal conserva sus velas');
  const firstAnalysisFetches=analysisFetches;
  eventSource.listeners.update();
  await new Promise(r=>setTimeout(r,180));
  assert.equal(analysisFetches,firstAnalysisFetches,'La misma vela/revisión no vuelve a consultar análisis');
  live={...live,series_revision:1,candles:[...live.candles,{...live.candles[live.candles.length-1],time:live.candles[live.candles.length-1].time+60,open:101,close:100.8}]};
  analysis=analysisFor('Bajista',1);analysis.last_candle_time=new Date(live.candles[live.candles.length-1].time*1000).toISOString();
  eventSource.listeners.update();
  await new Promise(r=>setTimeout(r,220));
  assert.equal(get('decision-bias').textContent,'Bajista');
  assert(analysisFetches>firstAnalysisFetches,'Una vela oficial nueva consulta el resultado cacheado');
  get('toggle-volume').listeners.click();
  assert.equal(get('toggle-volume').attributes['aria-pressed'],'true');
  assert(storage['traderassistant-v4-overlay-visibility'],'Se conserva el control de volumen');
  console.log(JSON.stringify({ui:'OK',analysis_fetches:analysisFetches,simulation_fetches:simulationFetches,live_fetches:liveFetches,candles:seriesState[0].data.length}));
})().catch(err=>{console.error(err);process.exit(1);});
