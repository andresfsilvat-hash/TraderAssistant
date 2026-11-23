'use strict';
// Prueba autocontenida de la UI (opcional: Node.js, no necesario en Windows).
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html=fs.readFileSync(require('path').join(__dirname,'..','realtime_v4','ui','live.html'),'utf8');
const source=html.split('<script>').pop().split('</script>')[0];
const elements=new Map();
const get=(id)=>{
  if(!elements.has(id))elements.set(id,{
    id,clientWidth:900,clientHeight:600,offsetWidth:500,style:{},textContent:'',
    className:'',classList:{add(){},remove(){},toggle(){}},
    addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn;}
  });
  return elements.get(id);
};
let setDataCount=0,updateCount=0;
const series=()=>({setData(items){setDataCount++;assert(Array.isArray(items));},update(){updateCount++;}});
const chart={addCandlestickSeries:series,addHistogramSeries:series,
  priceScale(){return {applyOptions(){}};},applyOptions(){},resize(){},
  timeScale(){return {setVisibleLogicalRange(){},scrollToRealTime(){}};}};
let eventSource;
class FakeEvents{
  constructor(url){assert.equal(url,'/api/alpaca/events');eventSource=this;}
  addEventListener(type,fn){this.listeners??={};this.listeners[type]=fn;}
}
class FakeResize {observe(){}}
let current={
  status:'conectado',symbol:'NVDA',version_info:'4.0.0',series_revision:0,
  candles:[{time:1700000040,open:150,high:151,low:149,close:150.5,volume:1000,provisional:false}],
  short_candles:[],trade_count:1,eligible_count:1,excluded_count:0,
  last_trade:{price:150.5,timestamp:'2023-11-14T22:14:01Z'},
  last_received_at:new Date().toISOString(),last_feed_message_at:new Date().toISOString(),
  last_lag_ms:120,error:null,history_error:null
};
const context={
  document:{getElementById:get},window:{addEventListener(){}},
  LightweightCharts:{createChart:()=>chart,CrosshairMode:{Normal:0}},
  EventSource:FakeEvents,ResizeObserver:FakeResize,
  Intl,Date,Math,Number,Array,Object,String,Error,
  setTimeout,clearTimeout,setInterval:()=>{},
  fetch:async()=>({ok:true,json:async()=>current})
};
(async()=>{
  vm.runInNewContext(source,context,{timeout:4000});
  await new Promise(r=>setTimeout(r,10));
  assert(setDataCount>=2,'La primera lectura dibuja velas y volumen');
  current={...current,series_revision:1,candles:[{...current.candles[0],close:150.1}]};
  eventSource.listeners.update();
  await new Promise(r=>setTimeout(r,180));
  assert(setDataCount>=4,'Una corrección de vela obliga a redibujar');
  assert.equal(get('version').textContent,'v4.0.0');
  assert(get('connection').textContent.includes('IEX'));
  get('tf5s').listeners.click();
  console.log('UI JavaScript: inicio, streaming, correccion y cambio de temporalidad OK');
})().catch(e=>{console.error(e);process.exit(1);});
