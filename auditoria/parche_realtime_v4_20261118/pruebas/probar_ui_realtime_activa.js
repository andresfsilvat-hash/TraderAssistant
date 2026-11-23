'use strict';
// Tests the exact UI installed at project_root/ui/live.html.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const projectRoot=process.env.TRADERASSISTANT_ROOT||path.resolve(__dirname,'..');
const uiPath=process.env.TRADERASSISTANT_REALTIME_UI||path.join(projectRoot,'ui','live.html');
const html=fs.readFileSync(uiPath,'utf8');
const matches=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert(matches.length,'No se encontro el script activo');
const source=matches[matches.length-1][1];
const elements=new Map();
const get=id=>{
  if(!elements.has(id))elements.set(id,{id,clientWidth:1000,clientHeight:600,offsetWidth:500,
    style:{},textContent:'',className:'',value:'NVDA',disabled:false,
    classList:{add(){},remove(){},toggle(){}},
    addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn;}});
  return elements.get(id);
};
const seriesData=[];
const series=()=>{const index=seriesData.length;seriesData.push([]);return {
  setData(items){assert(Array.isArray(items));seriesData[index]=items;},
  update(item){const data=seriesData[index];const last=data[data.length-1];
    if(last&&last.time===item.time)data[data.length-1]=item;else data.push(item);}};};
const chart={addCandlestickSeries:series,addLineSeries:series,addHistogramSeries:series,
  priceScale(){return {applyOptions(){}};},applyOptions(){},resize(){},
  timeScale(){return {setVisibleLogicalRange(){},scrollToRealTime(){}};}};
let eventSource;
class FakeEvents{constructor(url){assert.equal(url,'/api/alpaca/events');eventSource=this;}
  addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn;}}
class FakeResize{observe(){}}
const now=new Date().toISOString();
let current={status:'suscripcion_incompleta',symbol:'NVDA',symbol_name:'NVIDIA',version_info:'4.0.0',build:'test',
  series_revision:0,history_source:'alpaca',error:'Canales pendientes: quotes',history_error:null,
  market_clock:{source:'alpaca',phase:'PREMARKET',is_open:false,calendar_verified:true,checked_at:now,
    next_open:new Date(Date.now()+3600000).toISOString(),next_close:new Date(Date.now()+7*3600000).toISOString(),
    session_close:new Date(Date.now()+12*3600000).toISOString()},
  candles:[0,1,2,3,4].map((n)=>({time:1795008600+n*60,open:100+n,high:102+n,low:99+n,
    close:101+n,volume:10*(n+1),quality:'official',status:'closed',origin:'rest',provisional:false})),
  short_candles:[],quote_points:[],channel_status:{trades:true,quotes:false,bars:true,updatedBars:false},
  cache_status:{loaded_at:now,saved_at:now,error:null},trade_count:0,quote_count:1,eligible_count:0,
  last_trade:null,last_received_at:null,last_feed_message_at:now,
  last_quote:{bid:100,ask:100.2,mid:100.1,timestamp:now},last_quote_received_at:now,last_quote_lag_ms:20,
  quotes_subscribed:false,reconnect_count:0};
const context={document:{getElementById:get,title:''},window:{addEventListener(){}},
  LightweightCharts:{createChart:()=>chart,CrosshairMode:{Normal:0}},EventSource:FakeEvents,
  ResizeObserver:FakeResize,Intl,Date,Math,Number,Array,Object,String,Error,Map,
  setTimeout,clearTimeout,setInterval:()=>{},
  fetch:async(url,options)=>options?.method==='POST'?{ok:true,json:async()=>({symbol:'AAPL',status:'ok'})}:
    {ok:true,json:async()=>current}};
(async()=>{
  vm.runInNewContext(source,context,{timeout:5000,filename:uiPath});
  await new Promise(r=>setTimeout(r,30));
  assert.equal(get('regular-status').textContent,'PREMARKET');
  assert.equal(get('quote-spread').textContent,'$0.200');
  assert(get('channel-state').textContent.includes('quotes ×'));
  assert(get('bar-quality').textContent.includes('oficial'));
  get('tf5m').listeners.click();
  assert.equal(seriesData[0].length,1,'Cinco velas 1m forman una vela 5m');
  assert.deepEqual(seriesData[0][0],{time:1795008600,open:100,high:106,low:99,close:105});
  assert.equal(seriesData[2][0].value,150,'Volumen 5m agregado sin duplicacion');
  current={...current,series_revision:1,candles:current.candles.map((b,i)=>i===0?{...b,close:100.5}:b)};
  eventSource.listeners.update();
  await new Promise(r=>setTimeout(r,180));
  assert.equal(seriesData[0][0].open,100);
  console.log('UI activa OK:',uiPath);
})().catch(err=>{console.error(err);process.exit(1);});
