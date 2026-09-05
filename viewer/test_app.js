// Run with Node.js; tests races without requiring a graphical browser.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();const images=[];const pending=[];
const context=vm.createContext({Map,Set,Math,URLSearchParams,window:{},devicePixelRatio:1,Image:class{constructor(){images.push(this)}},document:{getElementById(id){if(!elements.has(id))elements.set(id,{textContent:'',className:'',style:{},innerHTML:''});return elements.get(id)}},fetch(url){return new Promise(resolve=>pending.push({url,resolve}))}});
let source=fs.readFileSync(__dirname+'/static/app.js','utf8');source=source.slice(0,source.indexOf("$('playButton').onclick="));vm.runInContext(source,context);
vm.runInContext("state.data={frames:[[0,'old.jpg']]};preloadFrame(0);state.generation++;state.data={frames:[[0,'new.jpg']]};state.frameLoading=new Set([0]);",context);
images[0].onload();assert.equal(vm.runInContext('state.frameReady.size',context),0);assert.equal(vm.runInContext('state.frameLoading.has(0)',context),true);
images[0].onerror();assert.equal(vm.runInContext('state.frameLoading.has(0)',context),true);
(async()=>{
  const old=vm.runInContext("loadEpisode('episode-1000')",context);
  vm.runInContext('state.generation++',context);
  pending[0].resolve({ok:true,json:async()=>({marker:'obsolete'})});await old;
  assert.equal(vm.runInContext('state.data',context),null);
  vm.runInContext('window.VIEWER_STATIC=true',context);
  assert.equal(vm.runInContext("apiUrl('episodes?offset=100')",context),'./api/episodes-100.json');
  assert.equal(vm.runInContext("apiUrl('episodes/episode-1000/chunks/2')",context),'./api/episodes/episode-1000/chunks/2.json');
  console.log('Viewer async isolation and static URL tests passed');
})().catch(error=>{console.error(error);process.exitCode=1});
