const $ = id => document.getElementById(id);
const state = {data:null,time:0,playing:false,speed:1,lastTick:0,frameIndex:-1,frameReady:new Map(),frameLoading:new Set()};
const colors = ['#72f1a7','#63d9e9','#b699ff','#ffc76b'];

function fmt(t) {
  t=Math.max(0,t||0); const m=Math.floor(t/60),s=t-m*60;
  return `${String(m).padStart(2,'0')}:${s.toFixed(2).padStart(5,'0')}`;
}
function nearest(rows,t) {
  if(!rows.length)return 0; let lo=0,hi=rows.length-1;
  while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(rows[mid][0]<=t)lo=mid;else hi=mid-1}
  return lo;
}
function preloadFrame(index) {
  const frames=state.data?.frames;if(!frames||index<0||index>=frames.length||state.frameReady.has(index)||state.frameLoading.has(index))return;
  state.frameLoading.add(index);const image=new Image();
  image.onload=()=>{state.frameLoading.delete(index);state.frameReady.set(index,image.src);if(index===nearest(state.data.frames,state.time))render(true)};
  image.onerror=()=>state.frameLoading.delete(index);
  image.src=frames[index][1];
}
function preloadWindow(index) {
  for(let i=index;i<Math.min(state.data.frames.length,index+40);i++)preloadFrame(i);
  if(state.frameReady.size>160)for(const key of state.frameReady.keys())if(key<index-20||key>index+80)state.frameReady.delete(key);
}
function sizeCanvas(canvas) {
  const dpr=Math.min(devicePixelRatio||1,2),r=canvas.getBoundingClientRect();
  const w=Math.max(1,Math.round(r.width*dpr)),h=Math.max(1,Math.round(r.height*dpr));
  if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}
  return {ctx:canvas.getContext('2d'),w,h,dpr};
}

async function loadEpisodes() {
  const list=await fetch('/api/episodes').then(r=>r.json());
  $('episodeSelect').innerHTML=list.map(e=>`<option value="${e.id}">${e.id.replace('episode-','Episode ')}</option>`).join('');
  $('episodeSelect').onchange=()=>loadEpisode($('episodeSelect').value);
  if(list.length)await loadEpisode(list[0].id);
}
async function loadEpisode(id) {
  state.playing=false;$('playButton').textContent='▶';$('statusPill').className='pill';
  $('statusPill').innerHTML='<i></i> Loading episode';
  const data=await fetch(`/api/episodes/${id}`).then(r=>{if(!r.ok)throw Error('Episode could not be loaded');return r.json()});
  state.data=data;state.time=0;state.frameIndex=-1;state.frameReady=new Map();state.frameLoading=new Set();preloadWindow(0);
  const m=data.manifest,mission=data.mission;
  $('missionInstruction').textContent=mission.instruction;$('seed').textContent=m.seed;
  $('duration').textContent=`${m.duration_s.toFixed(1)} s`;$('distance').textContent=`${m.path_length_m.toFixed(0)} m`;
  $('captureRate').textContent=`${m.camera.hz} Hz RGB`;$('endTime').textContent=fmt(m.duration_s);
  $('statusPill').className='pill ready';$('statusPill').innerHTML=`<i></i> ${m.status.toUpperCase()} · ${m.frame_count.toLocaleString()} frames`;
  render(true);drawChart();
}

function render(force=false) {
  const d=state.data;if(!d)return;const end=d.manifest.duration_s;
  state.time=Math.max(0,Math.min(end,state.time));
  const fi=nearest(d.frames,state.time),ai=nearest(d.actions,state.time),si=nearest(d.states,state.time);
  const frame=d.frames[fi],a=d.actions[ai],s=d.states[si],beforeCamera=state.time<d.frames[0][0];
  preloadWindow(fi);const ready=state.frameReady.get(fi);
  if(ready&&(force||fi!==state.frameIndex)){state.frameIndex=fi;$('rgbFrame').src=ready;$('frameCounter').textContent=`Frame ${(fi+1).toLocaleString()} / ${d.frames.length.toLocaleString()}`}
  $('frameEmpty').textContent=beforeCamera?'Waiting for the first camera frame':'Buffering preview frame…';
  $('frameEmpty').style.display=(beforeCamera||!ready)?'grid':'none';$('rgbFrame').style.visibility=beforeCamera?'hidden':'visible';
  $('scrubber').value=Math.round(state.time/end*1000);$('currentTime').textContent=fmt(state.time);$('cameraTime').textContent=`T+${fmt(frame[0])}`;
  updateAction(a);updateTelemetry(s);updateSubgoal(a);drawMap(s);drawChart();
}
function updateAction(a) {
  const vals=[a[1],a[2],a[3],a[4]],ids=['roll','pitch','yaw','throttle'];
  vals.forEach((v,i)=>{$(`${ids[i]}Value`).textContent=(v>=0?'+':'')+v.toFixed(2);$(`${ids[i]}Bar`).style.width=`${Math.max(0,Math.min(100,(v+1)*50))}%`});
  $('leftStick').querySelector('i').style.transform=`translate(${a[3]*34}px,${-a[4]*34}px)`;
  $('rightStick').querySelector('i').style.transform=`translate(${a[1]*34}px,${a[2]*34}px)`;
}
function updateTelemetry(s) {
  $('altitude').textContent=s[3].toFixed(1);$('speedValue').textContent=Math.hypot(s[4],s[5]).toFixed(1);
  $('heading').textContent=((s[9]*180/Math.PI+360)%360).toFixed(0)+'°';$('position').textContent=`${s[1].toFixed(0)} / ${s[2].toFixed(0)}`;
  $('armed').textContent=s[10]?'ARMED':'DISARMED';$('armed').className=s[10]?'armed on':'armed';$('waypointReadout').textContent=`WP ${String(s[11]+1).padStart(2,'0')}`;
}
function updateSubgoal(a) {
  const total=state.data.mission.waypoints_enu_m.length,wp=Math.min(total-1,a[5]);
  $('subgoal').textContent=a[6];$('subgoalIndex').textContent=String(wp+1).padStart(2,'0');$('subgoalProgress').textContent=`Waypoint ${wp+1} of ${total}`;
}

function mapTransform(wps,states,w,h) {
  const pts=wps.map(p=>[p[0],p[1]]).concat(states.map(s=>[s[1],s[2]]));
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);
  let minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const span=Math.max(maxX-minX,maxY-minY),worldPad=Math.max(14,span*.08);
  minX-=worldPad;maxX+=worldPad;minY-=worldPad;maxY+=worldPad;
  const pixelPad=16,scale=Math.min((w-2*pixelPad)/(maxX-minX||1),(h-2*pixelPad)/(maxY-minY||1));
  return p=>[pixelPad+(p[0]-minX)*scale,h-pixelPad-(p[1]-minY)*scale];
}
function visible(q,w,h,margin=8){return q[0]>=-margin&&q[0]<=w+margin&&q[1]>=-margin&&q[1]<=h+margin}
function polyline(ctx,points,tf){ctx.beginPath();points.forEach((p,i)=>{const q=tf(p);i?ctx.lineTo(...q):ctx.moveTo(...q)});ctx.stroke()}
function drawTriangle(ctx,x,y,r){ctx.beginPath();ctx.moveTo(x,y-r);ctx.lineTo(x-r*.85,y+r*.7);ctx.lineTo(x+r*.85,y+r*.7);ctx.closePath();ctx.fill()}
function drawDiamond(ctx,x,y,r){ctx.beginPath();ctx.moveTo(x,y-r);ctx.lineTo(x+r,y);ctx.lineTo(x,y+r);ctx.lineTo(x-r,y);ctx.closePath();ctx.fill()}

function drawEnvironment(ctx,env,tf,w,h,dpr) {
  if(!env)return;
  ctx.lineCap='round';ctx.lineJoin='round';
  ctx.strokeStyle='#263a32';ctx.lineWidth=14*dpr;ctx.globalAlpha=.72;polyline(ctx,env.river,tf);
  ctx.strokeStyle='#247f92';ctx.lineWidth=5*dpr;ctx.globalAlpha=.88;polyline(ctx,env.river,tf);ctx.globalAlpha=1;

  ctx.fillStyle='#315c3c';ctx.globalAlpha=.23;
  env.groundcover.forEach(p=>{const q=tf(p);if(visible(q,w,h)){ctx.beginPath();ctx.arc(q[0],q[1],Math.max(.7,Math.min(1.7,p[3]*.65))*dpr,0,Math.PI*2);ctx.fill()}});
  ctx.globalAlpha=.76;
  env.trees.forEach(p=>{const q=tf(p);if(visible(q,w,h)){ctx.fillStyle=p[2]==='mature-tree'?'#69a84f':p[2]==='fir'?'#287248':'#3b8b55';drawTriangle(ctx,q[0],q[1],p[2]==='mature-tree'?4.2*dpr:3.1*dpr)}});
  ctx.globalAlpha=.72;ctx.fillStyle='#9b9587';
  env.rocks.forEach(p=>{const q=tf(p);if(visible(q,w,h))drawDiamond(ctx,q[0],q[1],Math.max(1.1,Math.min(2.5,p[3]))*dpr)});
  ctx.fillStyle='#6e5140';ctx.globalAlpha=.72;
  env.debris.forEach(p=>{const q=tf(p);if(visible(q,w,h)){ctx.fillRect(q[0]-2*dpr,q[1]-.6*dpr,4*dpr,1.2*dpr)}});
  ctx.fillStyle='#bc9c78';ctx.globalAlpha=.88;
  env.rockslide.forEach(p=>{const q=tf(p);if(visible(q,w,h))drawDiamond(ctx,q[0],q[1],Math.max(2,Math.min(4,p[3]))*dpr)});
  ctx.fillStyle='#7c6a59';ctx.globalAlpha=.78;
  env.cliffs.forEach(p=>{const q=tf(p);if(visible(q,w,h))drawTriangle(ctx,q[0],q[1],p[2]==='cliff-gate'?5*dpr:3.5*dpr)});
  ctx.globalAlpha=1;

  env.landmarks.forEach(p=>{const q=tf(p);if(!visible(q,w,h,18))return;ctx.fillStyle='#f4a85f';ctx.strokeStyle='#171c19';ctx.lineWidth=2*dpr;ctx.beginPath();ctx.arc(q[0],q[1],4*dpr,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.font=`${9*dpr}px ui-sans-serif,system-ui`;ctx.textBaseline='middle';ctx.fillStyle='#dbe8e1';ctx.shadowColor='#07100e';ctx.shadowBlur=3*dpr;ctx.fillText(p[2],q[0]+7*dpr,q[1]-7*dpr);ctx.shadowBlur=0});
}

function drawMap(current) {
  const c=$('missionMap'),{ctx,w,h,dpr}=sizeCanvas(c),wps=state.data.mission.waypoints_enu_m,states=state.data.states;
  const tf=mapTransform(wps,states,w,h);ctx.clearRect(0,0,w,h);ctx.fillStyle='#091510';ctx.fillRect(0,0,w,h);
  ctx.strokeStyle='#1b2d27';ctx.lineWidth=dpr;
  for(let x=0;x<w;x+=40*dpr){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}
  for(let y=0;y<h;y+=40*dpr){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
  drawEnvironment(ctx,state.data.environment_map,tf,w,h,dpr);

  ctx.setLineDash([5*dpr,5*dpr]);ctx.strokeStyle='#a6bbb1';ctx.lineWidth=1.2*dpr;polyline(ctx,wps,tf);ctx.setLineDash([]);
  const upto=nearest(states,state.time);ctx.strokeStyle='#72f1a7';ctx.lineWidth=2*dpr;ctx.beginPath();
  for(let i=0;i<=upto;i+=2){const q=tf([states[i][1],states[i][2]]);i?ctx.lineTo(...q):ctx.moveTo(...q)}ctx.stroke();
  wps.forEach((p,i)=>{const q=tf(p);ctx.fillStyle=i===current[11]?'#ffc76b':'#172a23';ctx.strokeStyle=i===current[11]?'#ffc76b':'#9eb1a8';ctx.lineWidth=dpr;ctx.beginPath();ctx.arc(q[0],q[1],3.3*dpr,0,Math.PI*2);ctx.fill();ctx.stroke()});
  const q=tf([current[1],current[2]]);ctx.fillStyle='#ffc76b';ctx.shadowColor='#ffc76b';ctx.shadowBlur=12*dpr;ctx.beginPath();ctx.arc(q[0],q[1],6*dpr,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
}

function drawChart() {
  if(!state.data)return;const c=$('actionChart'),{ctx,w,h,dpr}=sizeCanvas(c),rows=state.data.actions,end=state.data.manifest.duration_s,pad=18*dpr;
  ctx.clearRect(0,0,w,h);ctx.strokeStyle='#20342c';ctx.lineWidth=dpr;
  for(let i=0;i<5;i++){const y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
  for(let axis=0;axis<4;axis++){ctx.strokeStyle=colors[axis];ctx.lineWidth=axis===3?1*dpr:1.2*dpr;ctx.globalAlpha=.86;ctx.beginPath();for(let i=0;i<rows.length;i+=4){const x=rows[i][0]/end*w,v=rows[i][axis+1],y=pad+(1-(v+1)/2)*(h-2*pad);i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()}
  ctx.globalAlpha=1;const x=state.time/end*w;ctx.strokeStyle='#edf7f1';ctx.lineWidth=dpr;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();ctx.fillStyle='#edf7f1';ctx.beginPath();ctx.arc(x,8*dpr,3*dpr,0,Math.PI*2);ctx.fill();
}

function tick(ts) {
  if(state.playing&&state.data){if(state.lastTick){const candidate=Math.min(state.data.manifest.duration_s,state.time+(ts-state.lastTick)/1000*state.speed),fi=nearest(state.data.frames,candidate);preloadWindow(fi);if(candidate<state.data.frames[0][0]||state.frameReady.has(fi))state.time=candidate}if(state.time>=state.data.manifest.duration_s){state.time=state.data.manifest.duration_s;state.playing=false;$('playButton').textContent='▶'}render()}
  state.lastTick=ts;requestAnimationFrame(tick);
}
$('playButton').onclick=()=>{if(!state.data)return;if(state.time>=state.data.manifest.duration_s)state.time=0;state.playing=!state.playing;$('playButton').textContent=state.playing?'❚❚':'▶'};
$('scrubber').oninput=e=>{if(state.data){state.time=e.target.value/1000*state.data.manifest.duration_s;render()}};
$('speed').onchange=e=>state.speed=+e.target.value;
$('skipBack').onclick=()=>{if(state.data){state.time=Math.max(0,state.time-.1);render()}};
$('skipForward').onclick=()=>{if(state.data){state.time=Math.min(state.data.manifest.duration_s,state.time+.1);render()}};
document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT'||e.target.tagName==='INPUT')return;if(e.code==='Space'){e.preventDefault();$('playButton').click()}if(e.code==='ArrowLeft')$('skipBack').click();if(e.code==='ArrowRight')$('skipForward').click()});
window.addEventListener('resize',()=>render(true));
loadEpisodes().catch(err=>{$('statusPill').innerHTML='<i></i> Viewer error';$('missionInstruction').textContent=err.message});
requestAnimationFrame(tick);
