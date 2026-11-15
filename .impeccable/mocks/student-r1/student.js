const rows=[
{id:1,q:'Q8',topic:'Density and units',lost:3,max:4,conf:58,why:'Unit missing in the final answer',crop:['ρ = m / V = 54 / 20','= 2.7','answer: 2.7'],scheme:'3 marks allowed without the unit; B1 for g/cm³.'},
{id:2,q:'Q4(b)',topic:'Algebra · simultaneous equations',lost:3,max:5,conf:64,why:'Sign error in the constant',crop:['x = 3y + 2  →  9y² + 12y + 4','so 9y² + 12y − 5 = 0','y = 0.33 or y = −1.67'],scheme:'A1 needs the constant −4; follow-through earns B1.'},
{id:3,q:'Q7',topic:'Geometry · area',lost:3,max:6,conf:82,why:'Method steps missing',crop:['area = ½ × 8 × 6','= 24','24 cm²'],scheme:null},
{id:4,q:'Q2(b)',topic:'Number · rearranging',lost:2,max:3,conf:66,why:'Answer unclear, 7 or 1',crop:['x ≈ 7. or 1?','check: 7 × 3 = 21','so x = 7'],scheme:'A1 only when x = 7 is unambiguous.'},
{id:5,q:'Q10',topic:'Statistics · averages',lost:2,max:3,conf:88,why:'Used the mode, not the mean',crop:['mode = 4','answer 4','—'],scheme:null},
{id:7,q:'Q3',topic:'Algebra · expanding',lost:2,max:3,conf:79,why:'Dropped a negative sign',crop:['(x − 2)(x + 3)','= x² + x − 6','x² + x + 6'],scheme:null},
{id:8,q:'Q1',topic:'Number · percentages',lost:1,max:3,conf:91,why:'Stopped one step early',crop:['15% of 80 = 12','80 − 12','= 68'],scheme:null},
{id:9,q:'Q5',topic:'Geometry · angles',lost:1,max:2,conf:85,why:'Reason not written',crop:['angle = 52°','answer 52'],scheme:null},
{id:6,q:'Q9',topic:'Trigonometry · ratios',lost:2,max:3,conf:74,why:'Rounded too early',crop:['cos 40° = 0.77','x = 12 × 0.77','x = 9.2'],scheme:null}];
rows.sort((a,b)=>b.lost-a.lost||a.conf-b.conf);
let lostTotal=19,trigger=null;
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let openId=null,sent=new Set(),ch=null,left=3,minLen=20,needTick=false;
const tone=c=>c<70?'var(--err)':'var(--gold)';
function vis(){let left=lostTotal;const out=[];for(const r of rows){if(left<=0)break;out.push({...r,lost:Math.min(r.lost,left)});left-=r.lost}return out}
function setLost(n){lostTotal=n;draw()}
const CHV=o=>`<svg width=16 height=16 viewBox="0 0 16 16" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="${o?'M3.5 10.5 8 6l4.5 4.5':'M3.5 5.5 8 10l4.5-4.5'}"/></svg>`;
function draw(){$('#rows').innerHTML=vis().map(r=>{const o=openId===r.id,low=r.conf<70;return `<div class="lr ${o?'open':''}" data-id="${r.id}"><button class=lh aria-expanded="${o}" data-toggle="${r.id}"><span class=win><b class=m>+${r.lost}</b><small>to win</small></span><span class=lt><b>${r.q} · ${r.topic}</b><span>${r.why}</span></span><span class=chev>${CHV(o)}</span></button>${o?`<div class=lb><div class=cr>${r.crop.map(t=>`<i>${t}</i>`).join('')}</div>${low&&r.scheme?`<div class=sch><span class=lab>Mark scheme</span><p>${r.scheme}</p></div>`:''}<div class=ra>${sent.has(r.id)?'<span class="chip ok">Challenge sent</span>':left<=0?'<span class="chip">No challenges left</span>':`<button class="btn t" data-challenge="${r.id}">Challenge this mark</button>`}<button class=btn data-practise="${r.topic.split(' · ')[0]}">Practise ${r.topic.split(' · ')[0]}</button></div></div>`:''}</div>`}).join('')+(lostTotal>rows.reduce((a,r)=>a+r.lost,0)?'<button class="btn t more2" data-more>Show all answers</button>':'');
$$('[data-lost]').forEach(e=>e.textContent=lostTotal)}
document.addEventListener('click',e=>{const t=e.target.closest('[data-toggle]');if(t){const id=+t.dataset.toggle;openId=openId===id?null:id;draw();return}
const c=e.target.closest('[data-challenge]');if(c){trigger=c;ch=+c.dataset.challenge;const r=rows.find(x=>x.id===ch);if(left<=0){toast('You have used all 3 challenges on this paper.');return}if(r.conf>=70&&$('#confirm')){$('#cq').textContent=r.q;$('#cc').textContent=r.conf;$('#confirm').classList.add('on');$('[data-keep]').focus();return}openSheet(r);return}
if(e.target.closest('[data-keep]')){closeDlg();return}
if(e.target.closest('[data-sure]')){$('#confirm').classList.remove('on');openSheet(rows.find(x=>x.id===ch));return}
if(e.target.closest('[data-close]')){closeDlg();return}
if(e.target.closest('[data-more]')){toast('Showing every answer…');return}
const pr=e.target.closest('[data-practise]');if(pr){toast('Building a '+pr.dataset.practise+' set…');return}
const nb=e.target.closest('.nx button');if(nb){toast(nb.textContent.trim()+'…');return}
if(e.target.closest('#retry')){setState('loading');setTimeout(()=>setState('ok'),900);return}
const stb=e.target.closest('[data-state]');if(stb){setState(stb.dataset.state);return}
if(e.target.closest('#send')&&!$('#send').disabled){sent.add(ch);left--;closeDlg(true);toast('Challenge sent. Ms. Hanna will take a look.');draw();return}
if(e.target.closest('[data-replay]')){document.body.classList.remove('revealed');$('#hold').style.setProperty('--hp',0);return}
if(e.target.closest('[data-share]')){toast('Share sheet: parent link or public card.');return}});
const check=()=>{const n=$('#why').value.trim().length;$('#send').disabled=n<minLen||(needTick&&!$('#tick').checked);$('#cnt').textContent=Math.min(n,minLen)+'/'+minLen+' min'};
$('#why').addEventListener('input',check);if($('#tick'))$('#tick').addEventListener('change',check);
function openSheet(r){const hi=r.conf>=70;minLen=hi?40:20;needTick=hi&&!!$('#tickrow');if($('#tickrow')){$('#tickrow').style.display=hi?'flex':'none';$('#tick').checked=false}$('#sheetq').textContent=r.q+' · '+r.topic;$('#sheetsub').textContent='Goes to Ms. Hanna (10B). '+left+' of 3 challenges left on this paper.';$('#sheet').classList.add('on');$('#why').value='';check();$('#why').focus()}
function closeDlg(sentOk){$('#confirm').classList.remove('on');$('#sheet').classList.remove('on');if(trigger&&!sentOk)trigger.focus();else if(sentOk){const t=$('[data-toggle="'+ch+'"]');t&&t.focus()}}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&($('#sheet').classList.contains('on')||$('#confirm').classList.contains('on')))closeDlg()});
function setState(st){document.body.classList.toggle('st-loading',st==='loading');document.body.classList.toggle('st-error',st==='error');$$('[data-state]').forEach(b=>b.classList.toggle('on',b.dataset.state===st))}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('on'),3500)}
// hold to reveal
const hold=$('#hold');let raf,t0,done=false;
function step(){const p=Math.min((performance.now()-t0)/900,1);hold.style.setProperty('--hp',p);if(p>=1){document.body.classList.add('revealed');return}raf=requestAnimationFrame(step)}
function start(e){if(document.body.classList.contains('revealed'))return;e.preventDefault();t0=performance.now();raf=requestAnimationFrame(step)}
function stop(){if(document.body.classList.contains('revealed'))return;cancelAnimationFrame(raf);hold.style.setProperty('--hp',0)}
hold.addEventListener('pointerdown',start);['pointerup','pointerleave','pointercancel'].forEach(n=>hold.addEventListener(n,stop));
hold.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&!e.repeat){document.body.classList.add('revealed');e.preventDefault()}});
draw();
