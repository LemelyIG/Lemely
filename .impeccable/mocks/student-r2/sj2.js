// Subject round 2: three grade paths on one aligned grid, a short Binny line, topic chips
const PATH=[['Oct','C',56,'0580/41 · Oct/Nov 2023'],['Dec','B',61,'0580/22 · Dec mock'],['Feb','B',63,'0580/42 · Feb/Mar 2024'],['Apr','A',76,'0580/42 · May/Jun 2024']];
const GOAL=['A*',85];
const GVV={'A*':'--ga','A':'--gA','B':'--gB','C':'--gC','D':'--gD'};
const FLAG='<svg width=14 height=14 viewBox="0 0 16 16" fill=none stroke=currentColor stroke-width=1.7 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M4 14V2.5M4 3h8l-2 3 2 3H4"/></svg>';
const N=PATH.length+1;
// shared label row: % and month under each column, so every path lines up the same way
const labels=`<div class=gp2l aria-hidden=true>${PATH.map((p,i)=>`<span${i===N-2?' class=cur':''}><b>${p[2]}%</b>${p[0]}</span>`).join('')}<span class=goal><b>${GOAL[1]}%</b>Goal</span></div>`;
const gap=GOAL[1]-PATH[N-2][2];

// A · Stones: round jewel tokens that climb with the mark, joined by one solid line
const yS2=p=>Math.round(104-(p-50)/40*84);
function stones(){const H=118,pts=[...PATH.map(p=>p[2]),GOAL[1]].map((v,i)=>[(i+.5)*100,yS2(v)]);
 const line=pts.slice(0,-1).map(p=>p.join(',')).join(' ');const [a,b]=[pts[N-2],pts[N-1]];
 return `<div class=gp2><div class="gp2t st" style="height:${H}px"><svg class=gp2s viewBox="0 0 ${N*100} ${H}" preserveAspectRatio=none aria-hidden=true><polyline points="${line}" fill=none stroke="oklch(.84 .015 240)" stroke-width=3 vector-effect=non-scaling-stroke stroke-linejoin=round /><line x1=${a[0]} y1=${a[1]} x2=${b[0]} y2=${b[1]} stroke="oklch(.86 .06 155)" stroke-width=6 stroke-linecap=round vector-effect=non-scaling-stroke /></svg>
 ${PATH.map((p,i)=>`<a class="stn${i===N-2?' cur':''}" style="--x:${(i+.5)/N*100}%;--y:${pts[i][1]}px;--c:var(${GVV[p[1]]})" data-go="Result: ${p[3]}" aria-label="${p[1]}, ${p[2]}%, ${p[0]}">${p[1]}</a>`).join('')}
 <a class="stn goal" style="--x:${(N-.5)/N*100}%;--y:${b[1]}px" data-go="Practice: what gets you to A*" aria-label="Goal A*, ${gap} points to go"><i>${FLAG}</i>A*</a>
 <span class=gp2gap style="--x:${(N-1)/N*100}%;--y:${Math.round((a[1]+b[1])/2)}px">+${gap}</span></div>${labels}</div>`}

// B · Steps: bars on one baseline, height = mark; the goal step is a soft solid block
function steps(){return `<div class=gp2 role=group aria-label="Grades so far: ${PATH.map(p=>p[1]+' in '+p[0]).join(', ')}. Goal A*, ${gap} points to go"><div class="gp2t sp">${PATH.map((p,i)=>`<a class="stp${i===N-2?' cur':''}" style="--h:${p[2]}%;--c:var(${GVV[p[1]]})" data-go="Result: ${p[3]}" aria-label="${p[1]}, ${p[2]}%, ${p[0]}"><b>${p[1]}</b></a>`).join('')}<a class="stp goal" style="--h:${GOAL[1]}%" data-go="Practice: what gets you to A*" aria-label="Goal A*, ${gap} points to go"><b>A*</b><span>+${gap}</span></a></div>${labels}</div>`}

// C · Rail: flat row of jewel tiles on one line, goal tile soft with a flag
function rail(){return `<div class=gp2><div class="gp2t rl">${PATH.map((p,i)=>`<a class="rlt${i===N-2?' cur':''}" style="--c:var(${GVV[p[1]]})" data-go="Result: ${p[3]}" aria-label="${p[1]}, ${p[2]}%, ${p[0]}">${p[1]}</a>`).join('')}<a class="rlt goal" data-go="Practice: what gets you to A*" aria-label="Goal A*, ${gap} points to go"><i>${FLAG}</i>A*</a></div>${labels}</div>`}

// Binny: two words and the button. The button carries the detail.
const say=(sz=60,mood='happy')=>`<div class=say2><div class=bwrap>${BIN(mood,sz)}</div><p class=bub2>Vectors first!</p></div><button class="btn big4 go2" data-go="Practice set: Vectors">Practise Vectors <span>· +9 marks</span></button>`;

const TOPICS=[['Number',82],['Algebra',58],['Functions',71],['Coordinate geometry',77],['Geometry',80],['Mensuration',69],['Trigonometry',62],['Vectors',41],['Probability',88],['Statistics',74]];
const lvl=v=>v>=75?'s':v>=60?'m':'w';
const DOT={s:'<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M2.5 6.3 5 8.6l4.5-5"/></svg>',m:'<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round aria-hidden=true><path d="M2.5 6h7"/></svg>',w:'<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round aria-hidden=true><path d="M6 2.5v7M2.5 6 6 9.5 9.5 6"/></svg>'};
const tmap=`<div class=tmap>${[...TOPICS].sort((a,b)=>a[1]-b[1]).map(t=>`<a class="tm ${lvl(t[1])}" data-go="Topic: ${t[0]}">${DOT[lvl(t[1])]}<span>${t[0]}</span><b>${t[1]}%</b></a>`).join('')}</div><div class=tleg><span><i class=w></i>Work on</span><span><i class=m></i>Getting there</span><span><i class=s></i>Secure</span></div>`;

const WT2=[['Vectors',9,1],['Algebra',7,0],['Trigonometry',5,1]];
const FCI='<svg width=18 height=18 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><rect x=3 y=5 width=11 height=12 rx=2 /><path d="M7 3h8a2 2 0 0 1 2 2v9"/></svg>';
const weak2=`<div class=win4><h2 class=sjh><a class="hlink h" data-go="Practice: Mathematics"><b>Win marks back</b>${SUB}</a></h2>${WT2.map(t=>`<div class=wrow2><a class=wmain data-go="Practice set: ${t[0]}"><span class=at><b>${t[0]}</b><span>Practise · 10 min</span></span><span class=wn>+${t[1]}<small> marks</small></span></a>${t[2]?`<a class=fc data-go="Flashcards: ${t[0]}" aria-label="${t[0]} flashcards">${FCI}</a>`:'<span class=fcx></span>'}</div>`).join('')}</div>`;
const papers=`<div class=win4><h2 class=sjh><a class="hlink h" data-go="All Mathematics papers"><b>Papers</b>${SUB}</a></h2>${[...PATH].reverse().map(p=>`<a class=rp data-go="Result: ${p[3]}"><b style="color:var(${GVV[p[1]]})">${p[1]}</b><span class=at><b>${p[3]}</b><span>${Math.round(p[2]*.8)}/80 · ${p[0]}</span></span>${CHEV}</a>`).join('')}</div>`;
const topics=`<div class=sec7><h2 class=sjh><a class="hlink h" data-go="Topic map"><b>Topics</b>${SUB}</a></h2>${tmap}</div>`;
const hd=`<div class=sjhd><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><div class=t><h1>Mathematics</h1><span class=s>0580 · 4 papers</span></div><a class=pill4 data-go="Study plan: exam dates">${CAL}188 days${SUB}</a></div>`;
const pathHd=`<h2 class=sjh><a class="hlink h" data-go="Mathematics progress"><b>Your path to A*</b>${SUB}</a></h2>`;
const phone=path=>`${hd}<div class=sjpad><section class=sec7>${pathHd}${path}</section><section class=tip2>${say()}</section>${weak2}${topics}${papers}</div>${TAB6('')}`;
put('SA',phone(stones()));put('SB',phone(steps()));put('SC',phone(rail()));
put('SAD',`${DRAIL6('Subjects')}<div class=dmain><header class=dtop><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><h1>Mathematics</h1><a class=pill4 data-go="Study plan: exam dates">${CAL}188 days to Paper 4${SUB}</a></header><div class=sjd><section class=sjl><section class=sec7>${pathHd}${stones()}</section><section class=tip2>${say(72)}</section>${weak2}</section><section class=sjr>${topics}${papers}</section></div></div>`);
put('SBD',`${DRAIL6('Subjects')}<div class=dmain><header class=dtop><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><h1>Mathematics</h1><a class=pill4 data-go="Study plan: exam dates">${CAL}188 days to Paper 4${SUB}</a></header><div class=sjd><section class=sjl><section class=sec7>${pathHd}${steps()}</section><section class=tip2>${say(72)}</section>${weak2}</section><section class=sjr>${topics}${papers}</section></div></div>`);
