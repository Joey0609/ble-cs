const stages = [
  ['Why indoors', 'senswear-1'], ['SensWear', 'senswear-6'],
  ['Channel Sounding', 'senswear-9'], ['Positioning', 'senswear-37'],
  ['Hands-on', 'technical-07-toolchain'], ['Reference', 'senswear-10']
];
const deck = document.querySelector('.reveal .slides');
const notesPanel = document.getElementById('notes-panel');
let schedule = [];
let noteEntries = new Map();
function breadcrumb(stage) {
  const current = stages.findIndex(s => s[0] === stage);
  return '<ol>'+stages.slice(0, stage === 'Reference' ? 6 : 5).map(([label,id],i) =>
    `<li class="${i===current?'current':i<current?'complete':'upcoming'}"><a href="#/${id}"${i===current?' aria-current="step"':''}>${label}</a></li>`
  ).join('')+'</ol>';
}
function stamp(seconds) {
  return `${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`;
}
function sync() {
  const slide = Reveal.getCurrentSlide();
  if (!slide) return;
  const record = noteEntries.get(slide.id);
  document.body.dataset.surface = 'dark';
  fitTechnicalSlide(slide);
  const main = schedule.filter(s=>!s.optional);
  const optional = schedule.filter(s=>s.optional);
  const index = (record?.optional ? optional : main).findIndex(s=>s.id===slide.id);
  document.getElementById('slide-counter').textContent = record?.optional
    ? `Reference ${index+1} / ${optional.length}` : `${String(index+1).padStart(2,'0')} / ${main.length}`;
  notesPanel.replaceChildren();
  const h = document.createElement('h3'); h.textContent = record?.title || 'Speaker notes'; notesPanel.append(h);
  const timing = document.createElement('p'); timing.className='presenter-timing';
  timing.textContent=record?.optional?'Supplementary material':`${stamp(record?.startSeconds||0)}–${stamp(record?.endSeconds||0)} · ${record?.stage||''}`;
  notesPanel.append(timing);
  const original = slide.querySelector(':scope > aside.notes');
  if (original) {
    const copy=original.cloneNode(true); copy.className='presenter-copy'; copy.removeAttribute('hidden');
    copy.querySelector('h3')?.remove(); notesPanel.append(copy);
  } else {
    const p = document.createElement('p');p.textContent=record?.notes || 'Use the slide diagram and invite questions.';notesPanel.append(p);
  }
}
function toggleNotes() { notesPanel.hidden = !notesPanel.hidden; sync(); }

function makeHeader(stage) {
  const header=document.createElement('div');header.className='eyebrow';
  header.innerHTML='<span>SensWear / IPIN 2026</span><nav class="breadcrumb" aria-label="Tutorial progress">'+breadcrumb(stage)+'</nav>';
  return header;
}

// Figure labels, coordinates, paths and timings are copied verbatim. Inline
// SVGs allow the shared CSS palette to style the original vector artwork.
async function inlineTechnicalFigures(slide) {
  await Promise.all([...slide.querySelectorAll('img[src$=".svg"]')].map(async img=>{
    const response=await fetch(img.getAttribute('src'));
    if(!response.ok)throw new Error(`Could not load ${img.getAttribute('src')}`);
    const svg=new DOMParser().parseFromString(await response.text(),'image/svg+xml').documentElement;
    if(svg.localName!=='svg')throw new Error('Invalid SVG figure');
    svg.setAttribute('class',img.className+' themed-figure');
    svg.setAttribute('role','img');svg.setAttribute('aria-label',img.alt);
    svg.dataset.originalSource=img.getAttribute('src');
    img.replaceWith(document.importNode(svg,true));
  }));
}

function decorateTechnical(slide) {
  slide.classList.add('technical-slide');
  const heading=slide.querySelector(':scope > h1, :scope > h2, :scope > h3');
  if(heading)heading.classList.add('slide-title');
  const content=document.createElement('div');content.className='technical-content';
  const body=document.createElement('div');body.className='technical-body';
  [...slide.childNodes].forEach(node=>{
    if(node!==heading&&!(node.nodeType===1&&node.matches('aside.notes')))body.append(node);
  });
  content.append(body);slide.prepend(makeHeader(slide.dataset.stage));
  if(heading)heading.after(content);else slide.append(content);
}

function fitTechnicalSlide(slide) {
  if(!slide?.classList.contains('technical-slide'))return;
  const title=slide.querySelector('.slide-title'),content=slide.querySelector('.technical-content'),body=slide.querySelector('.technical-body');
  const top=title?title.offsetTop+title.offsetHeight+24:100;
  content.style.top=top+'px';
  const available=720-56-top;
  const scale=Math.min(1, available/body.scrollHeight);
  body.style.setProperty('--content-scale',scale);
  body.style.left=(1160*(1-scale)/2)+'px';
  slide.dataset.contentScale=scale.toFixed(4);
}

try {
  const responses = await Promise.all(['integration/slide-order.json','integration/run-of-show.json'].map(p=>fetch(p)));
  if (responses.some(r=>!r.ok)) throw new Error('Could not load the slide order or presenter schedule.');
  const order = await responses[0].json(); schedule=await responses[1].json();
  noteEntries=new Map(schedule.map(s=>[s.id,s]));
  const fragments=await Promise.all(order.map(async entry=>{
    const response=await fetch(entry.file);
    if (!response.ok) throw new Error(`${entry.file}: HTTP ${response.status}`);
    return response.text();
  }));
  const slidePromises=order.map(async (entry,index)=>{
    const template=document.createElement('template');template.innerHTML=fragments[index];
    const root=template.content.querySelector('section');
    if (!root) throw new Error(`No slide in ${entry.file}`);
    const children=[...root.querySelectorAll(':scope > section')];
    const leaves=entry.child!==undefined?[children[entry.child]]:children.length?children:[root];
    for (const [i,slide] of leaves.entries()) {
      if(!slide)throw new Error(`Missing section in ${entry.file}`);
      slide.id=entry.child!==undefined?entry.id:children.length?`${entry.id}-${i+1}`:entry.id;
      slide.dataset.source=entry.file;
      if(children.length)slide.classList.add(...root.classList);
      slide.dataset.stage=entry.stage;slide.dataset.optional=String(entry.optional);
      slide.dataset.backgroundColor='#09242b';
      if (entry.kind==='senswear') {
        slide.classList.add('story-slide');slide.classList.remove('light');
        const nav=slide.querySelector('.breadcrumb'); if(nav)nav.innerHTML=breadcrumb(entry.stage);
      } else {
        decorateTechnical(slide);
        await inlineTechnicalFigures(slide);
      }
    }
    return leaves;
  });
  // Preserve manifest order even when figure fetches complete out of order.
  for(const slides of await Promise.all(slidePromises))deck.append(...slides);
  // Interactives attach only after all imported controls have been inserted.
  await new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src='senswear/interactives.js';
    script.onload=resolve;script.onerror=reject;document.body.append(script);
  });
  Reveal.on('ready',sync); Reveal.on('slidechanged',sync);
  Reveal.on('resize',()=>fitTechnicalSlide(Reveal.getCurrentSlide()));
  await Reveal.initialize({
    width:1280,height:720,margin:0.04,center:false,hash:true,
    transition:'none',backgroundTransition:'none',controls:true,progress:true,
    slideNumber:false,overview:true,help:true,pdfSeparateFragments:false,
    plugins:[RevealNotes,RevealHighlight,RevealMath.KaTeX],
    katex:{local:'vendor/katex'}, keyboard:{78:toggleNotes}
  });
  await document.fonts.ready;
  // KaTeX is loaded asynchronously by the Reveal plugin. Refit the current
  // figure when equations or fonts alter its intrinsic content height.
  const observer=new ResizeObserver(()=>fitTechnicalSlide(Reveal.getCurrentSlide()));
  document.querySelectorAll('.technical-body').forEach(body=>observer.observe(body));
  sync();
  document.getElementById('notes-toggle').onclick=toggleNotes;
  document.querySelectorAll('input,button,select').forEach(el=>el.addEventListener('keydown',e=>{
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown',' '].includes(e.key))e.stopPropagation();
  }));
} catch (error) {
  deck.replaceChildren();const slide=document.createElement('section');
  const title=document.createElement('h2');title.textContent='Open the tutorial through its local server';
  const instruction=document.createElement('p');instruction.textContent='Run START-INTEGRATED.cmd or npm start in this folder. See INTEGRATION.md.';
  const detail=document.createElement('p');detail.textContent=String(error.message||error);
  slide.append(title,instruction,detail);deck.append(slide);
  Reveal.initialize({width:1280,height:720});
}
