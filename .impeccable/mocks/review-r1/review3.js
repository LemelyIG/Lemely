const TICK='<svg class="tick" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5 6.5 11.5 12.5 4.5"/></svg>';
const items=[
{id:1,who:'Layla Hassan',cls:'10B',paper:'0580/42 · m/j 2025',q:'Q4(b)',why:'Sign error in constant',conf:64,max:5,scheme:'A1 needs −4, found −5',crop:['x = 3y + 2  →  9y² + 12y + 4','so 9y² + 12y − 5 = 0','y = 0.33 or y = −1.67'],pts:[['M1','Expands the bracket',1,0],['M1','Collects to zero',1,0],['A1','Constant −4 (exact)',1,'a'],['B1','Follow-through quadratic',1,'a'],['M1','Solves quadratic',1,0],['A1','Both roots',1,0]],on:[0,1,3,4]},
{id:2,who:'Omar Saleh',cls:'10A',paper:'0625/22 · o/n 2024',q:'Q8',why:'Unit missing',conf:58,max:4,scheme:'3 marks allowed without unit',crop:['ρ = m / V = 54 / 20','= 2.7','answer: 2.7'],pts:[['M1','Uses ρ = m/V',1,0],['A1','2.7',1,0],['B1','g/cm³ stated',1,0],['B1','Mass and volume read from graph',1,0]],on:[0,1,3]},
{id:3,who:'Nour Adel',cls:'10B',paper:'0580/42 · m/j 2025',q:'Q2(b)',why:'Handwriting unclear',conf:66,max:3,scheme:'7 or 1, ambiguous',crop:['x ≈ 7. or 1?','check: 7 × 3 = 21','so x = 7'],pts:[['M1','Sets up equation',1,0],['M1','Isolates x',1,0],['A1','x = 7',1,0]],on:[0,1]},
{id:4,who:'Youssef Karim',cls:'11C',paper:'0606/12 · m/j 2025',q:'Q10',why:'Alternative method',conf:69,max:3,scheme:'Method not in scheme',crop:['area = ½ × b × h','= ½ × 8 × 6','= 24 cm²'],pts:[['M1','Valid area method',1,0],['M1','Substitutes values',1,0],['A1','24',1,0]],on:[0,1,2]},
{id:5,who:'Mariam Fouad',cls:'10A',paper:'0625/21 · o/n 2024',q:'Q3(a)',why:'Rounding differs',conf:72,max:3,scheme:'2 s.f. required',crop:['v² = u² + 2as','v² = 0 + 2×9.8×4','v = 8.85 m/s'],pts:[['M1','Substitutes',1,0],['A1','v = 8.9',1,0],['B1','2 s.f.',1,0]],on:[0]},
{id:6,who:'Karim Samir',cls:'11C',paper:'0580/42 · m/j 2025',q:'Q9',why:'Integrity flag · similar answer',conf:74,max:3,scheme:'Matches another script',flag:1,crop:['cos 40° = 0.77','x = 12 × 0.77','x = 9.2'],pts:[['M1','Trig ratio',1,0],['M1','Rearranges',1,0],['A1','9.2',1,0]],on:[0,1,2]}];
const EX={1: ["low", "Q4(b) asks for the constant of the quadratic after expanding. Award A1 for −4; follow-through B1 if the quadratic is consistent.", "“I think I made a sign slip in the constant.”"], 2: ["low", "Density from the graph. M1 formula, A1 2.7, B1 unit g/cm³ (not awarded if absent, max 3), B1 readings.", "“I forgot the unit.”"], 3: ["unclear", "Q2(b): set up, isolate x, final answer 7. Accept 7 only when unambiguous.", "No self-review yet."], 4: ["alt", "Any valid area method earns M1. Substitute then answer 24.", "“Used a different method, hope it counts.”"], 5: ["low", "Substitute into v² = u² + 2as; answer to 2 s.f.", "“Not sure about rounding.”"], 6: ["flag", "Trig ratio, rearrange, answer 9.2.", "No self-review yet."]};
items.forEach(i=>{i.orig=[...i.on];i.state='open';[i.reason,i.full,i.self]=EX[i.id];i.changed=0});
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
let focus=items[0],undo=null,sel=false,picked=new Set(),F={reason:new Set(),cls:new Set(),paper:new Set(),q:'',sort:'lost'},menu=null,view='crop',dismissed=0,changed=0;
const total=i=>i.on.length,open=()=>items.filter(i=>i.state==='open');
const rowHTML=i=>{const t=i.conf<70?'var(--err)':'var(--gold)';return `<div class="row ${i===focus?'on':''}" data-id="${i.id}" tabindex=0 role=button><span class="ck ${i.flag?'na':''} ${picked.has(i.id)?'is':''}">${picked.has(i.id)?TICK:''}</span><span class=ring style="--v:${i.conf};--t:${t}"><span class=m>${i.conf}<small>%</small></span></span><div class=rb><div class=nm><b>${i.who}</b> <span class=sub>${i.cls} · ${i.q}</span></div><div class=why><i class=dot style="background:${t}"></i>${i.why}</div></div><div class=sc><span class=m>${total(i)}/${i.max}</span></div></div>`};
const vis=i=>(!F.reason.size||F.reason.has(i.reason))&&(!F.cls.size||F.cls.has(i.cls))&&(!F.paper.size||F.paper.has(i.paper.slice(0,4)))&&(!F.q||(i.who+' '+i.paper+' '+i.q+' '+i.why).toLowerCase().includes(F.q.toLowerCase()));
const sorted=()=>[...items].sort((a,b)=>F.sort==='lost'?(b.max-total(b))-(a.max-total(a)):F.sort==='conf'?a.conf-b.conf:a.id-b.id);
function panel(){const i=focus;if(!i){$('#panel').innerHTML='';return}
const ex=n=>i.pts.some((p,k)=>p[3]&&k!==n&&p[3]===i.pts[n][3]&&i.on.includes(k));
let h='',last=null;i.pts.forEach((p,k)=>{if(p[3]&&last===p[3])h+='<div class=or>OR</div>';last=p[3];h+=`<button class="tk ${i.on.includes(k)?'is':''}" data-k="${k}" ${ex(k)?'disabled':''}><span class=bx>${i.on.includes(k)?TICK:''}</span><span><b class=code>${p[0]}</b> ${p[1]}</span><span class=pt>${p[2]}</span></button>`});
const vs=vis,list=sorted().filter(x=>x.state==='open'&&vs(x)),pos=list.indexOf(i)+1,d=total(i)-i.orig.length;
const page=`<div class="cr pg"><div class=pgh>Page 6 of 20 · 0580/42</div><i style="opacity:.55">Q4(a) factorise x² − 5x + 6</i><i style="opacity:.55">(x − 2)(x − 3)</i><div class=bxd><i style="margin:0">${i.crop[0]}</i></div><i style="opacity:.55">Q5 area = ½ × 8 × 6</i></div>`;
$('#panel').innerHTML=`<div class=ph><button class="btn o bk" data-back aria-label="Back to the queue"><svg width=18 height=18 viewBox="0 0 18 18" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M11 4 6 9l5 5"/></svg>Queue</button><div style="flex:1;min-width:0"><h2>${i.who} · ${i.q}</h2><div class=sub>${i.cls} · ${i.paper}</div></div><div class=nav><button data-nav=-1 aria-label="Previous answer" ${pos<=1?'disabled':''}><svg width=18 height=18 viewBox="0 0 18 18" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M11 4 6 9l5 5"/></svg></button><span class="m">${pos||'–'} of ${list.length}</span><button data-nav=1 aria-label="Next answer" ${pos>=list.length?'disabled':''}><svg width=18 height=18 viewBox="0 0 18 18" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="m7 4 5 5-5 5"/></svg></button></div></div>
<div class=vt role=tablist><button data-view=crop class="${view==='crop'?'on':''}">Answer</button><button data-view=page class="${view==='page'?'on':''}">Whole page</button></div>${view==='crop'?`<div class=cr>${i.crop.map(t=>`<i>${t}</i>`).join('')}</div>`:page}
<div class=sr><span class=lab>Student said</span><div>${i.self}</div></div>
<div class=ctl><div class=step><button data-d=-1 ${total(i)<=0?'disabled':''} aria-label="One mark less">−</button><span class=m>${total(i)}/${i.max}</span><button data-d=1 ${total(i)>=i.max?'disabled':''} aria-label="One mark more">+</button></div><span class="m sub">${d===0?'as marked by Lemely':(d>0?'+':'−')+Math.abs(d)+' from Lemely'}</span></div>
<div style="display:grid;gap:6px">${h}</div><details class=sch><summary>Mark scheme wording</summary><p>${i.full}</p></details><textarea class=note rows=2 placeholder="Note to student (optional)"></textarea><div class=acts><button class=btn data-act=acc style="flex:1">${d===0?'Accept':'Save'} ${total(i)}/${i.max}</button><button class="btn o" data-act=dis>Dismiss…</button></div>`}
function render(){const o=open(),n=items.length,d=n-o.length,list=sorted();
if(focus&&(focus.state!=='open'||!vis(focus))){focus=list.find(x=>x.state==='open'&&vis(x))||null}
$('#list').innerHTML=list.map(rowHTML).join('');$$('.row').forEach(r=>{const it=items.find(x=>x.id==r.dataset.id);if(it.state!=='open')r.classList.add('gone');else if(!vis(it))r.style.display='none'});
const l=$('[data-left]');$$('[data-left]').forEach(e=>{if(e.textContent!=o.length){e.textContent=o.length;e.classList.remove('bump');void e.offsetWidth;e.classList.add('bump')}});$$('[data-done]').forEach(e=>e.textContent=d);$$('[data-total]').forEach(e=>e.textContent=n);$$('[data-fill]').forEach(e=>e.style.width=(d/n*100)+'%');
$('#sum').textContent=`${n} decided · ${changed} marks changed · ${dismissed} dismissed`;
const cleared=!o.length;$('#done').classList.toggle('on',cleared);$('#panelwrap').style.visibility=cleared?'hidden':'visible';$('#list').style.display=cleared?'none':'grid';$('#filters').style.display=cleared?'none':'grid';document.body.classList.toggle('cleared',cleared);
const clearN=o.filter(i=>!i.flag&&i.conf>=70&&vis(i)).length;const bk=$('#bulk');if(sel){bk.textContent=picked.size?`Approve ${picked.size} selected`:'Pick answers to approve';bk.disabled=!picked.size}else{bk.textContent=clearN?`Approve ${clearN} clear`:'No clear answers';bk.disabled=!clearN}$$('[data-selbtn]').forEach(e=>e.textContent=sel?'Cancel':'Select');
chips();const shownN=sorted().filter(x=>x.state==='open'&&vis(x)).length,filt=F.reason.size||F.cls.size||F.paper.size||F.q;$('#shown').textContent=`Showing ${shownN} of ${o.length}`;$('#shown').style.display=filt&&o.length?'block':'none';$('#nomatch').classList.toggle('on',!!(o.length&&!shownN));panel()}
function finish(i,msg){if(msg.includes('dismissed'))dismissed++;else if(total(i)!==i.orig.length)changed++;i.state='done';document.body.classList.remove('detail');undo=i;picked.delete(i.id);const nx=open()[0];focus=nx||null;$('#toast span').textContent=msg;$('#toast').classList.add('on');clearTimeout(finish.t);finish.t=setTimeout(()=>$('#toast').classList.remove('on'),5000);render()}
document.addEventListener('click',e=>{
if(e.target.closest('[data-clearf]')){F.reason.clear();F.cls.clear();F.paper.clear();F.q='';$('#q').value='';render();return}
if(e.target.closest('#menu-btn')){openNav(true);return}if(e.target.closest('[data-closenav]')||e.target.closest('#drawer a')){openNav(false);return}
const stb=e.target.closest('[data-state]');if(stb){setState(stb.dataset.state);return}
if(e.target.closest('#retry')){setState('loading');setTimeout(()=>setState('ok'),900);return}
const rmc=e.target.closest('[data-rm]');if(rmc){const [k,v]=rmc.dataset.rm.split('|');F[k].delete(v);render();return}
if(e.target.closest('#addf')){menu=menu?null:{step:'cat'};drawMenu();return}
const mc=e.target.closest('[data-cat]');if(mc){menu={step:mc.dataset.cat};drawMenu();return}
const mv=e.target.closest('[data-val]');if(mv){const [k,v]=mv.dataset.val.split('|');F[k].has(v)?F[k].delete(v):F[k].add(v);render();drawMenu();return}
if(e.target.closest('[data-menuback]')){menu={step:'cat'};drawMenu();return}
if(menu&&!e.target.closest('#menu')){menu=null;drawMenu()}
if(e.target.closest('[data-back]')){document.body.classList.remove('detail');return}
const nv=e.target.closest('[data-nav]');if(nv){const l=sorted().filter(x=>x.state==='open'&&vis(x)),x=l.indexOf(focus)+ +nv.dataset.nav;if(l[x]){focus=l[x];render()}return}
const vw=e.target.closest('[data-view]');if(vw){view=vw.dataset.view;panel();return}
const r=e.target.closest('.row');if(r){const i=items.find(x=>x.id==r.dataset.id);if(sel){if(i.flag)return;picked.has(i.id)?picked.delete(i.id):picked.add(i.id)}else{focus=i;document.body.classList.add('detail')}render();return}
const t=e.target.closest('.tk');if(t&&!t.disabled){const k=+t.dataset.k,i=focus;i.on.includes(k)?i.on=i.on.filter(x=>x!==k):i.on.push(k);panel();$$('.row.on .sc .m').forEach(x=>x.textContent=total(i)+'/'+i.max);return}
const s=e.target.closest('.step button');if(s){const i=focus,d=+s.dataset.d;if(d>0){const k=i.pts.findIndex((p,k)=>!i.on.includes(k)&&!(p[3]&&i.on.some(j=>i.pts[j][3]===p[3])));if(k>-1)i.on.push(k)}else i.on.pop();panel();$$('.row.on .sc .m').forEach(x=>x.textContent=total(i)+'/'+i.max);return}
const a=e.target.closest('[data-act]');if(a){const i=focus;if(a.dataset.act==='acc')finish(i,`${i.q} saved at ${total(i)}/${i.max}.`);else finish(i,`${i.q} dismissed.`);return}
if(e.target.closest('[data-sel]')){sel=!sel;document.body.classList.toggle('sel',sel);picked.clear();render();return}
if(e.target.closest('[data-bulk]')){const ids=sel?[...picked]:open().filter(i=>!i.flag&&i.conf>=70).map(i=>i.id);ids.forEach(id=>{const i=items.find(x=>x.id==id);i.state='done'});undo=null;focus=open()[0]||null;picked.clear();sel=false;document.body.classList.remove('sel');$('#toast span').textContent=`${ids.length} approved.`;$('#toast').classList.add('on');setTimeout(()=>$('#toast').classList.remove('on'),4000);render();return}
if(e.target.closest('#undo')){if(undo){undo.state='open';focus=undo;undo=null;$('#toast').classList.remove('on');render()}return}
if(e.target.closest('[data-reset]')){items.forEach(i=>{i.state='open';i.on=[...i.orig]});focus=sorted()[0];dismissed=0;changed=0;F={reason:new Set(),cls:new Set(),paper:new Set(),q:'',sort:'lost'};$('#q').value='';drawSort();render()}});
document.addEventListener('keydown',e=>{if(e.target.tagName==='TEXTAREA')return;const o=open();const k=e.key;if(k==='j'||k==='k'){const x=o.indexOf(focus);focus=o[Math.max(0,Math.min(o.length-1,x+(k==='j'?1:-1)))];render()}if(k==='a'&&focus)finish(focus,`${focus.q} saved at ${total(focus)}/${focus.max}.`)});
render();

focus=sorted()[0];render();

const OPT={reason:[['low','Low confidence'],['unclear','Unclear handwriting'],['alt','Alternative method'],['flag','Integrity flag']],cls:[['10A','10A'],['10B','10B'],['11C','11C']],paper:[['0580','0580 Mathematics'],['0606','0606 Add. Maths'],['0625','0625 Physics']]};
const LBL={reason:'Reason',cls:'Class',paper:'Paper'};
function chips(){let h='';for(const k of ['reason','cls','paper'])for(const v of F[k]){const o=OPT[k].find(x=>x[0]===v);h+=`<span class=rm>${LBL[k]}: ${o?o[1]:v} <u data-rm="${k}|${v}" role=button aria-label="Remove filter">×</u></span>`}
$('#chips').innerHTML=h+`<button class=add id=addf>+ Filter</button>`}
function drawMenu(){const m=$('#menu');if(!menu){m.style.display='none';return}m.style.display='block';
if(menu.step==='cat'){m.innerHTML='<div class=gl>Filter by</div>'+Object.keys(LBL).map(k=>`<button class=it data-cat="${k}">${LBL[k]}${F[k].size?` <span class=badge>${F[k].size}</span>`:''}<span class=mm>›</span></button>`).join('')}
else{const k=menu.step;m.innerHTML=`<button class=it data-menuback>‹ ${LBL[k]}</button>`+OPT[k].map(([v,l])=>`<button class=it data-val="${k}|${v}"><span class="cb ${F[k].has(v)?'is':''}">${F[k].has(v)?TICK:''}</span>${l}</button>`).join('')}}
$('#q').addEventListener('input',e=>{F.q=e.target.value.trim();render()});
const SORTS=[['lost','Marks lost'],['conf','Confidence'],['id','Oldest']];let sortOpen=false;
function drawSort(){$('#sortlbl').textContent=SORTS.find(x=>x[0]===F.sort)[1];const m=$('#sortmenu');m.style.display=sortOpen?'block':'none';$('#sortbtn').setAttribute('aria-expanded',sortOpen);m.innerHTML=SORTS.map(([v,l])=>`<button class="it ${F.sort===v?'is':''}" role=menuitemradio aria-checked="${F.sort===v}" data-sort="${v}">${l}<span class=mm>${F.sort===v?TICK:''}</span></button>`).join('')}
document.addEventListener('click',e=>{const sb=e.target.closest('#sortbtn');if(sb){sortOpen=!sortOpen;drawSort();return}const so=e.target.closest('[data-sort]');if(so){F.sort=so.dataset.sort;sortOpen=false;drawSort();render();return}if(sortOpen&&!e.target.closest('#sortmenu')){sortOpen=false;drawSort()}});
drawSort();
document.addEventListener('keydown',e=>{if(e.key==='/'&&e.target.tagName!=='INPUT'&&e.target.tagName!=='TEXTAREA'){e.preventDefault();$('#q').focus()}if(e.key==='Escape'){if(menu){menu=null;drawMenu()}if(typeof sortOpen!=='undefined'&&sortOpen){sortOpen=false;drawSort()}}});
chips();

function openNav(on){$('#drawer').classList.toggle('on',on);$('#menu-btn').setAttribute('aria-expanded',on);if(on)$('#drawer a.on').focus();else $('#menu-btn').focus()}
function setState(st){document.body.classList.toggle('st-loading',st==='loading');document.body.classList.toggle('st-error',st==='error');$$('[data-state]').forEach(b=>b.classList.toggle('on',b.dataset.state===st))}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('#drawer').classList.contains('on'))openNav(false)});
render();
