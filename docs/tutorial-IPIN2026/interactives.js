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
// Frequency offset to range bias: |Δd| = c·ε·Δt/2, the same for phase and time.
function updateCal(){
  const eps=+$('cal-eps').value,dt=+$('cal-dt').value,bias=(e,t)=>C*e*1e-6*t*1e-6/2,ymax=2;
  const x=v=>75+v/50*900,y=v=>235-v/ymax*190;
  let out=txt(78,22,'Range bias (m)');
  for(let i=0;i<=4;i++){const v=ymax*i/4;out+=lin(75,y(v),975,y(v))+txt(22,y(v)+5,v.toFixed(1));}
  for(const p of [0,10,20,30,40,50])out+=lin(x(p),45,x(p),235)+txt(x(p)-10,263,p.toString());
  out+=txt(420,287,'Frequency offset ε (ppm)');
  out+=`<rect x="${x(0)}" y="45" width="${x(1)-x(0)}" height="190" fill="${colors.lime}" opacity=".18"/>`+txt(x(1)+8,62,'≤ 1 ppm',colors.lime,15);
  for(const [t,label] of [[69,'tone gap 69 µs'],[176,'turnaround 176 µs']])out+=lin(x(0),y(0),x(50),y(bias(50,t)),colors.muted,'6 6')+txt(x(50)-150,y(bias(50,t))-8,label,colors.muted,15);
  out+=`<path d="M${x(0)},${y(0)} L${x(50)},${y(bias(50,dt))}" stroke="${colors.teal}" stroke-width="3" fill="none"/><circle cx="${x(eps)}" cy="${y(bias(eps,dt))}" r="7" fill="${colors.orange}"/>`;
  $('cal-chart').innerHTML=out;$('cal-eps-label').textContent=eps.toFixed(1)+' ppm';$('cal-dt-label').textContent=dt+' µs';
  const b=bias(eps,dt);$('cal-output').textContent=`Δf = ${(eps*2.44).toFixed(1)} kHz at 2.44 GHz   |   range bias: ${b<1?(b*100).toFixed(1)+' cm':b.toFixed(2)+' m'}`;
  $('cal-pbr').classList.toggle('active',dt===69);$('cal-rtt').classList.toggle('active',dt===176);
}
['cal-eps','cal-dt'].forEach(id=>$(id).addEventListener('input',updateCal));
$('cal-pbr').onclick=()=>{$('cal-dt').value=69;updateCal();};$('cal-rtt').onclick=()=>{$('cal-dt').value=176;updateCal();};updateCal();
// Screenshots can be enlarged in the room without leaving the deck.
const zoom=document.createElement('div');zoom.className='image-overlay';zoom.hidden=true;zoom.setAttribute('role','dialog');zoom.setAttribute('aria-label','Enlarged application screenshot');zoom.innerHTML='<span>Click or press Esc to close</span><img alt="Enlarged actual application screenshot">';document.body.appendChild(zoom);
zoom.onclick=()=>zoom.hidden=true;
document.querySelectorAll('.screenshot-frame img').forEach(img=>{img.title='Click to enlarge';img.tabIndex=0;img.setAttribute('role','button');const open=()=>{zoom.querySelector('img').src=img.src;zoom.hidden=false;};img.onclick=open;img.onkeydown=e=>{if(e.key==='Enter'){e.stopPropagation();open();}};});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!zoom.hidden){e.stopImmediatePropagation();e.preventDefault();zoom.hidden=true;}},true);
