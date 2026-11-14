// Subject · final. Steps path per paper (P2 / P4), marks as the only unit, goal = the real A* line.
{
const GVV={'A*':'--ga','A':'--gA','B':'--gB','C':'--gC','D':'--gD'};
const PAPERS={
 p4:{name:'Paper 4',out:80,line:68,src:'May/Jun 2024 boundary',rows:[['Oct','C',45,'0580/41 · Oct/Nov 2023'],['Jan','B',48,'0580/43 · Jan mock'],['Feb','B',50,'0580/42 · Feb/Mar 2024'],['Apr','A',61,'0580/42 · May/Jun 2024']]},
 p2:{name:'Paper 2',out:70,line:60,src:'May/Jun 2024 boundary',rows:[['Nov','B',44,'0580/22 · Oct/Nov 2023'],['Dec','B',47,'0580/22 · Dec mock'],['Mar','A',53,'0580/21 · Feb/Mar 2024']]},
};
const ALL=[...PAPERS.p4.rows.map(r=>[...r,80]),...PAPERS.p2.rows.map(r=>[...r,70])];
const ORDER=['Apr','Mar','Feb','Jan','Dec','Nov','Oct'];
const gapOf=P=>P.line-P.rows.at(-1)[2];
// bars run from 40% of the marks up to the A* line, so each grade reads as a real step and the goal is the top
const hOf=(P,m)=>Math.max(0,Math.round((m-P.out*.4)/(P.line-P.out*.4)*100));
const ghostBar='<span class="stp ghost" aria-hidden=true></span>';
function steps(P,{ghosts=0}={}){const n=P.rows.length,gap=gapOf(P);
 const lab=`<div class=gp2l aria-hidden=true style="--n:${n+ghosts+1}">${P.rows.map((r,i)=>`<span${i===n-1?' class=cur':''}><b>${r[2]}<small>/${P.out}</small></b>${r[0]}</span>`).join('')}${'<span class=gl0>next</span>'.repeat(ghosts)}<span class=goal><b>${P.line}<small>/${P.out}</small></b>A* line</span></div>`;
 return `<div class=gp2 role=group aria-label="${P.name} marks so far: ${P.rows.map(r=>`${r[1]}, ${r[2]} out of ${P.out} in ${r[0]}`).join('; ')}. The A* line is ${P.line}, ${gap} marks to go."><div class="gp2t sp" style="--n:${n+ghosts+1}">${P.rows.map((r,i)=>`<a class="stp${i===n-1?' cur':''}" style="--h:${hOf(P,r[2])}%;--c:var(${GVV[r[1]]})" data-go="Result: ${r[3]}" aria-label="${r[1]}, ${r[2]} out of ${P.out}, ${r[0]}"><b>${r[1]}</b></a>`).join('')}${ghostBar.repeat(ghosts)}<a class="stp goal" style="--h:100%" data-go="How the A* line is set: ${P.src}" aria-label="A* line, ${P.line} out of ${P.out}. ${gap} marks to go"><b>A*</b><span>${gap} to go</span></a></div>${lab}</div>`}
const tog=(on,id)=>`<div class=ptog role=tablist aria-label="Choose a paper">${Object.entries(PAPERS).sort().reverse().map(([k,P])=>`<button role=tab aria-selected=${k===on} data-pt="${id}:${k}">${P.name}</button>`).join('')}</div>`;
// forecast and trend from the live screen, as one plain line
const trend=P=>{const r=P.rows,up=r.at(-1)[2]-r[0][2];return `<p class=trend2>Heading for an <b style="color:var(--gA)">A</b> · up ${up} marks since ${r[0][0]}</p>`};
const H2=(go,t,extra='')=>`<div class=h2row><h2 class=sjh><a class="hlink h" data-go="${go}"><b>${t}</b>${SUB}</a></h2>${extra}</div>`;
const pathSec=(k,id)=>`<section class=sec7 id="${id}-path">${H2('Mathematics progress','Your path to A*',tog(k,id))}<div class=pbody>${steps(PAPERS[k])}${trend(PAPERS[k])}</div></section>`;

const say=(t,go,goSub,sz=60,mood='happy')=>`<div class=say2><div class=bwrap>${BIN(mood,sz)}</div><p class=bub2>${t}</p></div><button class="btn big4 go2" data-go="${go}">${goSub}</button>`;
const tip=sz=>`<section class=tip2>${say(`${gapOf(PAPERS.p4)} marks to A*!`,'Practice set: Vectors','Practise Vectors <span>· +9 marks</span>',sz)}</section>`;

const TOPICS=[['Number',82],['Algebra',58],['Functions',71],['Coordinate geometry',77],['Geometry',80],['Mensuration',69],['Trigonometry',62],['Vectors',41],['Probability',88],['Statistics',74]];
const lvl=v=>v>=75?'s':v>=60?'m':'w';
const IC={s:'<path d="M2.5 6.3 5 8.6l4.5-5"/>',m:'<path d="M2.5 6h7"/>',w:'<circle cx=6 cy=6 r=3.6 /><circle cx=6 cy=6 r=.6 fill=currentColor />'};
const ic=l=>`<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true>${IC[l]}</svg>`;
const CH='<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="m4.5 2.5 3.5 3.5-3.5 3.5"/></svg>';
const chip=t=>`<a class="tm ${lvl(t[1])}" data-go="Topic: ${t[0]}">${ic(lvl(t[1]))}<span>${t[0]}</span><b>${t[1]}%</b></a>`;
const LEG=`<div class=tleg><span>${ic('w')}Work on</span><span>${ic('m')}Getting there</span><span>${ic('s')}Secure</span></div>`;
const sorted=[...TOPICS].sort((a,b)=>a[1]-b[1]);
const topics=fold=>`<div class=sec7>${H2('Topic map','Topics')}<div class=tmap>${(fold?sorted.filter(t=>lvl(t[1])!=='s'):sorted).map(chip).join('')}${fold?`<a class="tm s more" data-go="Topic map: secure topics">${ic('s')}<span>4 secure</span><b>${CH}</b></a>`:''}</div>${LEG}</div>`;

const FCI='<svg width=18 height=18 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><rect x=3 y=5 width=11 height=12 rx=2 /><path d="M7 3h8a2 2 0 0 1 2 2v9"/></svg>';
const wrow=t=>`<div class=wrow2><a class=wmain data-go="Practice set: ${t[0]}"><span class=at><b>${t[0]}</b><span>Practise · 10 min</span></span><span class=wn>+${t[1]}<small> marks</small></span></a>${t[2]?`<a class=fc data-go="Flashcards: ${t[0]}" aria-label="${t[0]} flashcards">${FCI}</a>`:'<span class=fcx></span>'}</div>`;
// Vectors already has Binny's button, so the list starts with the next ones
const win=`<div class=win4>${H2('Practice: Mathematics','More marks to win')}${[['Algebra',7,1],['Trigonometry',5,1],['Mensuration',4,0]].map(wrow).join('')}</div>`;
const prow=p=>`<a class=rp data-go="Result: ${p[3]}"><b style="color:var(${GVV[p[1]]})">${p[1]}</b><span class=at><b>${p[3]}</b><span>${p[2]}/${p[4]} · ${p[0]}</span></span>${CHEV}</a>`;
const papers=n=>`<div class=win4>${H2('All Mathematics papers','Papers')}${[...ALL].sort((a,b)=>ORDER.indexOf(a[0])-ORDER.indexOf(b[0])).slice(0,n).map(prow).join('')}${n<ALL.length?`<a class=morel data-go="All Mathematics papers">All ${ALL.length} papers${CH}</a>`:''}</div>`;

const PILL=(t)=>`<a class=pill4 data-go="Study plan: exam dates">${CAL}${t}${SUB}</a>`;
const hd=`<div class=sjhd><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><div class=t><h1>Mathematics</h1><span class=s>IGCSE · 0580 · Extended</span></div>${PILL('188 days')}</div>`;
const tabSub=TAB6('').replace('<a data-go="Subjects tab">','<a class=on aria-current=page data-go="Subjects tab">');
const phone=body=>`${hd}<div class=sjpad>${body}</div>${tabSub}`;
const dtop=`<header class=dtop><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><div class=t2><h1>Mathematics</h1><span class=s>IGCSE · 0580 · Extended</span></div>${PILL('188 days to Paper 4')}</header>`;
const desk=(l,r)=>`${DRAIL6('Subjects')}<div class=dmain>${dtop}<div class=sjd><section class=sjl>${l}</section><section class=sjr>${r}</section></div></div>`;
// tablet: top-bar tabs (768–1279), same two columns, narrower gap
const TTOP=`<nav class=ttop2><span class=brand2>lemely</span>${['Home','Practice','Subjects','Me'].map(t=>`<a class="${t==='Subjects'?'on':''}" ${t==='Subjects'?'aria-current=page':''} data-go="${t}">${t}</a>`).join('')}<button class="btn o scan2" data-go="Scan">${CAM.replace('width=26 height=26','width=18 height=18')} Scan</button></nav>`;

// ---------- full ----------
const fullP=id=>phone(`${pathSec('p4',id)}${tip()}${win}${topics(1)}${papers(4)}`);
put('F_P',fullP('F_P'));
put('F_D',desk(`${pathSec('p4','F_D')}${tip(72)}${win}`,`${topics(0)}${papers(5)}`));
put('F_T',`${TTOP}<div class=tpad>${dtop.replace('class=dtop','class="dtop t"')}<div class="sjd t"><section class=sjl>${pathSec('p4','F_T')}${tip(64)}${win}</section><section class=sjr>${topics(1)}${papers(4)}</section></div></div>`);

// ---------- first run: no papers in this subject yet (the live 404) ----------
const GH={name:'Paper 4',out:80,line:68,rows:[]};
const ghostPath=`<div class="gp2 ghostp" aria-hidden=true><div class="gp2t sp" style="--n:5">${[30,45,52,70].map(h=>`<span class="stp ghost" style="--h:${h}%"></span>`).join('')}<span class="stp goal" style="--h:100%"><b>A*</b></span></div><div class=gp2l style="--n:5">${'<span></span>'.repeat(4)}<span class=goal>A* line</span></div></div>`;
const STEPS=[['Scan a Maths paper','Any past paper you have tried. Phone camera or PDF.'],['Lemely marks it','Every question, with method marks. About two minutes.'],['Your path appears','Each paper adds a step towards the A* line.']];
const walk=`<ol class=walk2>${STEPS.map((s,i)=>`<li><span class=wn2>${i+1}</span><span class=at><b>${s[0]}</b><span>${s[1]}</span></span></li>`).join('')}</ol>`;
const firstBody=sz=>`<section class=sec7><h2 class=sjh2>Your path to A*</h2>${ghostPath}</section><section class=tip2>${say('Let’s find your first step!','Scan','Scan a Maths paper',sz,'open')}<a class="lnk q upl" data-go="Upload a PDF">Upload a PDF instead</a></section>${walk}`;
put('Z_P',phone(firstBody()));
put('Z_D',desk(firstBody(72),`<div class=sec7><h2 class=sjh2>Topics</h2><p class=hint2>Your strong and weak topics show up here after your first paper.</p><div class="tmap ghostc" aria-hidden=true>${['w','m','s','m','s','w','s','m'].map((l,i)=>`<span class="tm ${l}" style="width:${[96,120,88,140,104,92,128,110][i]}px"></span>`).join('')}</div></div><div class=sec7><h2 class=sjh2>Papers</h2><p class=hint2>Every Maths paper you mark lands here, newest first.</p></div>`));

// ---------- sparse: one paper marked ----------
const ONE={name:'Paper 4',out:80,line:68,src:'May/Jun 2024 boundary',rows:[['Apr','A',61,'0580/42 · May/Jun 2024']]};
const oneBody=`<section class=sec7>${H2('Mathematics progress','Your path to A*')}<div class=pbody>${steps(ONE,{ghosts:3})}<p class=trend2>One step so far. Two more papers show your trend.</p></div></section><section class=tip2>${say('Great start! Next paper?','Scan','Scan your next paper')}</section><div class=win4>${H2('Practice: Mathematics','Marks to win')}${[['Vectors',9,1],['Algebra',7,1]].map(wrow).join('')}</div><div class=sec7>${H2('Topic map','Topics')}<div class=tmap>${[['Vectors',41],['Algebra',58],['Trigonometry',62],['Number',82]].map(chip).join('')}</div><p class=hint2>4 of 10 topics so far. Each paper fills in more.</p></div>${`<div class=win4>${H2('All Mathematics papers','Papers')}${prow([...ONE.rows[0],80])}</div>`}`;
put('S_P',phone(oneBody));

// ---------- loading + error ----------
const skel=`<div class=sk2c aria-busy=true aria-label="Loading Mathematics"><span class="sk" style="width:150px;height:22px"></span><div class=skbars>${[38,50,56,84,100].map(h=>`<span class=sk style="height:${h}%"></span>`).join('')}</div><span class=sk style="height:50px;border-radius:16px"></span>${'<span class=sk style="height:52px"></span>'.repeat(3)}</div>`;
put('L_P',phone(skel));
put('E_P',phone(`<div class=err2><div class=bwrap>${BIN('sad',96)}</div><h2>We couldn’t load Mathematics</h2><p>Check your connection, then try again. Your papers are safe.</p><button class="btn big4 go2" data-go="Retry">Try again</button><a class="lnk q" data-go="Back to Subjects">Back to Subjects</a></div>`));

// paper toggle repaints that frame's path
document.addEventListener('click',e=>{const b=e.target.closest('[data-pt]');if(!b)return;const [id,k]=b.dataset.pt.split(':');const s=document.getElementById(id+'-path');s.querySelectorAll('[data-pt]').forEach(x=>x.setAttribute('aria-selected',x===b));s.querySelector('.pbody').innerHTML=steps(PAPERS[k])+trend(PAPERS[k])});
}
