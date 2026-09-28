/* Original teaching models. All data are synthetic; no hardware performance claim. */
const C=299792458,TAU=2*Math.PI;
const colors={ink:'#f5f5ed',muted:'#afc8cb',teal:'#65e4d0',lime:'#dcf58a',orange:'#ffb17a',line:'#31535a'};
const $=s=>document.getElementById(s);
const txt=(x,y,t,color=colors.muted,size=18)=>`<text x="${x}" y="${y}" fill="${color}" font-family="Segoe UI,Arial" font-size="${size}">${t}</text>`;
const lin=(x,y,X,Y,color=colors.line,dash='')=>`<line x1="${x}" y1="${y}" x2="${X}" y2="${Y}" stroke="${color}" stroke-width="2" stroke-dasharray="${dash}"/>`;
function updateRTT(){
  const d=+$('rtt-distance').value,turn=+$('rtt-turn').value,ns=2*d/C*1e9;
  $('rtt-values').innerHTML=`<div class="formula small">d = ${d.toFixed(0)} m</div><p class="small">Reflector turnaround: <strong>${turn.toFixed(0)} µs</strong><br>Initiator elapsed: <strong>${(turn+ns/1000).toFixed(5)} µs</strong></p><div class="formula small">Corrected RTT = ${ns.toFixed(2)} ns</div>`;
}
['rtt-distance','rtt-turn'].forEach(id=>$(id).addEventListener('input',updateRTT));updateRTT();
function unwrap(a){let out=[a[0]];for(let i=1;i<a.length;i++){let delta=a[i]-a[i-1];while(delta>Math.PI)delta-=TAU;while(delta<=-Math.PI)delta+=TAU;out.push(out[i-1]+delta);}return out;}
function fit(x,y){const xm=x.reduce((a,b)=>a+b,0)/x.length,ym=y.reduce((a,b)=>a+b,0)/y.length;let num=0,den=0;for(let i=0;i<x.length;i++){num+=(x[i]-xm)*(y[i]-ym);den+=(x[i]-xm)**2;}return num/den;}
function updatePBR(){
  const d=+$('pbr-distance').value,wrapped=$('pbr-wrap').checked,echo=$('pbr-echo').checked;
  const f=[],phase=[];
  for(let ch=2;ch<=76;ch++){if([23,24,25].includes(ch))continue;const hz=(2402+ch)*1e6,p=-TAU*hz*d/C,ep=-TAU*hz*(d+4)/C,re=Math.cos(p)+(echo?.42*Math.cos(ep):0),im=Math.sin(p)+(echo?.42*Math.sin(ep):0);f.push(hz);phase.push(Math.atan2(2*re*im,re*re-im*im));}
  const un=unwrap(phase),estimate=-C*fit(f,un)/(4*Math.PI);let data=wrapped?phase:un.map(v=>v-un[0]);let lo=wrapped?-Math.PI:Math.min(...data)-.3,hi=wrapped?Math.PI:Math.max(...data)+.3;
  const x=v=>75+(v-2404e6)/(74e6)*900,y=v=>235-(v-lo)/(hi-lo)*190;
  let out=txt(78,22,wrapped?'Wrapped two-way phase (rad)':'Unwrapped phase change (rad)');
  for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;out+=lin(75,y(v),975,y(v))+txt(12,y(v)+5,v.toFixed(1));}
  for(const mhz of [2404,2424,2444,2464,2478])out+=lin(x(mhz*1e6),45,x(mhz*1e6),235)+txt(x(mhz*1e6)-22,263,mhz.toString());
  out+=txt(460,287,'Frequency (MHz)');let path='';
  for(let i=0;i<data.length;i++){const cut=i===0||(wrapped&&Math.abs(data[i]-data[i-1])>Math.PI);path+=(cut?'M':'L')+x(f[i]).toFixed(2)+','+y(data[i]).toFixed(2)+' ';}
  out+=`<path d="${path}" fill="none" stroke="${echo?colors.orange:colors.teal}" stroke-width="3"/>`;
  for(let i=0;i<data.length;i++)out+=`<circle cx="${x(f[i])}" cy="${y(data[i])}" r="3" fill="${echo?colors.orange:colors.teal}"/>`;
  $('pbr-chart').innerHTML=out;$('pbr-distance-label').textContent=d.toFixed(1)+' m';$('pbr-output').textContent=`True: ${d.toFixed(2)} m   |   simple slope estimate: ${estimate.toFixed(2)} m${echo?'   |   echo amplitude: 0.42':''}`;
}
['pbr-distance','pbr-wrap','pbr-echo'].forEach(id=>$(id).addEventListener('input',updatePBR));updatePBR();
function updateGeometry(clustered=false){
 const p=[6,4],anchors=clustered?[[.5,3.1],[.5,3.7],[.5,4.3],[.5,4.9]]:[[1,1],[11,1],[1,7],[11,7]],sigma=.25;
 let aa=0,ab=0,bb=0;for(const a of anchors){const dx=p[0]-a[0],dy=p[1]-a[1],r=Math.hypot(dx,dy),ux=dx/r,uy=dy/r;aa+=ux*ux;ab+=ux*uy;bb+=uy*uy;}
 const det=aa*bb-ab*ab,c00=sigma*sigma*bb/det,c01=-sigma*sigma*ab/det,c11=sigma*sigma*aa/det;
 const trace=c00+c11,disc=Math.sqrt((c00-c11)**2+4*c01*c01),major=Math.sqrt((trace+disc)/2),minor=Math.sqrt((trace-disc)/2),angle=.5*Math.atan2(2*c01,c00-c11);
 const X=x=>115+x*60,Y=y=>270-y*30;let s='';
 // Keep equal metric scales by drawing the 12 m x 8 m room at 30 px/m.
 const xx=x=>180+x*30,yy=y=>270-y*30;
 for(let i=0;i<=12;i++)s+=lin(xx(i),yy(0),xx(i),yy(8));for(let i=0;i<=8;i++)s+=lin(xx(0),yy(i),xx(12),yy(i));
 anchors.forEach((a,i)=>{s+=lin(xx(a[0]),yy(a[1]),xx(p[0]),yy(p[1]),colors.teal,'5 5');s+=`<rect x="${xx(a[0])-6}" y="${yy(a[1])-6}" width="12" height="12" fill="${colors.teal}"/>`;s+=txt(xx(a[0])+10,yy(a[1])-6,'A'+(i+1),colors.teal,16);});
 let path='';for(let i=0;i<=100;i++){const t=i/100*TAU,dx=major*Math.cos(t)*Math.cos(angle)-minor*Math.sin(t)*Math.sin(angle),dy=major*Math.cos(t)*Math.sin(angle)+minor*Math.sin(t)*Math.cos(angle);path+=(i?'L':'M')+xx(p[0]+dx)+','+yy(p[1]+dy);}
 s+=`<path d="${path}Z" stroke="${colors.orange}" fill="#ffb17a22" stroke-width="3"/><circle cx="${xx(p[0])}" cy="${yy(p[1])}" r="5" fill="${colors.lime}"/>`;
 s+=txt(635,75,'Same target. Same range noise.',colors.ink,25)+txt(635,125,'1σ major axis: '+major.toFixed(2)+' m',colors.orange,24)+txt(635,165,'1σ minor axis: '+minor.toFixed(2)+' m',colors.teal,24)+txt(635,215,'Ellipse drawn to the room scale.',colors.muted,18)+txt(180,25,'12 m × 8 m · floor plane',colors.muted,18);
 $('geometry-chart').innerHTML=s;$('geometry-output').textContent=clustered?'Clustered bearings weaken cross-range observability.':'Surrounding anchors provide diverse range directions.';
 $('geom-wide').classList.toggle('active',!clustered);$('geom-wall').classList.toggle('active',clustered);
}
$('geom-wide').onclick=()=>updateGeometry(false);$('geom-wall').onclick=()=>updateGeometry(true);updateGeometry();
// Screenshots can be enlarged in the room without leaving the deck.
const zoom=document.createElement('div');zoom.className='image-overlay';zoom.hidden=true;zoom.setAttribute('role','dialog');zoom.setAttribute('aria-label','Enlarged application screenshot');zoom.innerHTML='<span>Click or press Esc to close</span><img alt="Enlarged actual application screenshot">';document.body.appendChild(zoom);
zoom.onclick=()=>zoom.hidden=true;
document.querySelectorAll('.screenshot-frame img').forEach(img=>{img.title='Click to enlarge';img.tabIndex=0;img.setAttribute('role','button');const open=()=>{zoom.querySelector('img').src=img.src;zoom.hidden=false;};img.onclick=open;img.onkeydown=e=>{if(e.key==='Enter'){e.stopPropagation();open();}};});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!zoom.hidden){e.stopImmediatePropagation();e.preventDefault();zoom.hidden=true;}},true);
