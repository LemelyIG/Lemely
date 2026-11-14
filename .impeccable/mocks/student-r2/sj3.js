// Subject · B (Steps). Marks are the only unit; the goal is the real A* line for the next paper.
{
const PATH=[['Oct','C',45,'0580/41 · Oct/Nov 2023'],['Dec','B',49,'0580/22 · Dec mock'],['Feb','B',50,'0580/42 · Feb/Mar 2024'],['Apr','A',61,'0580/42 · May/Jun 2024']];
const OUT=80,GOAL=['A*',68,'May/Jun 2024 boundary'];
const GVV={'A*':'--ga','A':'--gA','B':'--gB','C':'--gC','D':'--gD'};
const N=PATH.length+1,gap=GOAL[1]-PATH[N-2][2];
// bars run from 40% of the marks up to the A* line, so each grade reads as a real step and the goal is the top
const h=m=>Math.round((m-OUT*.4)/(GOAL[1]-OUT*.4)*100);
const labels=`<div class=gp2l aria-hidden=true>${PATH.map((p,i)=>`<span${i===N-2?' class=cur':''}><b>${p[2]}<small>/${OUT}</small></b>${p[0]}</span>`).join('')}<span class=goal><b>${GOAL[1]}<small>/${OUT}</small></b>A* line</span></div>`;
const steps=()=>`<div class=gp2 role=group aria-label="Marks so far: ${PATH.map(p=>`${p[1]}, ${p[2]} out of ${OUT} in ${p[0]}`).join('; ')}. The A* line is ${GOAL[1]}, ${gap} marks to go."><div class="gp2t sp">${PATH.map((p,i)=>`<a class="stp${i===N-2?' cur':''}" style="--h:${h(p[2])}%;--c:var(${GVV[p[1]]})" data-go="Result: ${p[3]}" aria-label="${p[1]}, ${p[2]} out of ${OUT}, ${p[0]}"><b>${p[1]}</b></a>`).join('')}<a class="stp goal" style="--h:${h(GOAL[1])}%" data-go="How the A* line is set: ${GOAL[2]}" aria-label="A* line, ${GOAL[1]} out of ${OUT}. ${gap} marks to go"><b>A*</b><span>${gap} to go</span></a></div>${labels}</div>`;

// Binny points at the goal; the button names the way there
const say=(sz=60)=>`<div class=say2><div class=bwrap>${BIN('happy',sz)}</div><p class=bub2>${gap} marks to A*!</p></div><button class="btn big4 go2" data-go="Practice set: Vectors">Practise Vectors <span>· +9 marks</span></button>`;

const TOPICS=[['Number',82],['Algebra',58],['Functions',71],['Coordinate geometry',77],['Geometry',80],['Mensuration',69],['Trigonometry',62],['Vectors',41],['Probability',88],['Statistics',74]];
const lvl=v=>v>=75?'s':v>=60?'m':'w';
const ICO={s:'<path d="M2.5 6.3 5 8.6l4.5-5"/>',m:'<path d="M2.5 6h7"/>',w:'<circle cx=6 cy=6 r=3.6 /><circle cx=6 cy=6 r=.6 fill=currentColor />'};
const ic=l=>`<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true>${ICO[l]}</svg>`;
const chip=t=>`<a class="tm ${lvl(t[1])}" data-go="Topic: ${t[0]}">${ic(lvl(t[1]))}<span>${t[0]}</span><b>${t[1]}%</b></a>`;
const LEG=`<div class=tleg><span>${ic('w')}Work on</span><span>${ic('m')}Getting there</span><span>${ic('s')}Secure</span></div>`;
const sorted=[...TOPICS].sort((a,b)=>a[1]-b[1]);
// phone folds the secure topics into one chip; desktop has room for all
const tmapP=`<div class=tmap>${sorted.filter(t=>lvl(t[1])!=='s').map(chip).join('')}<a class="tm s more" data-go="Topic map: secure topics">${ic('s')}<span>4 secure</span><b>${'<svg width=12 height=12 viewBox="0 0 12 12" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="m4.5 2.5 3.5 3.5-3.5 3.5"/></svg>'}</b></a></div>${LEG}`;
const tmapD=`<div class=tmap>${sorted.map(chip).join('')}</div>${LEG}`;

const H2=(go,t)=>`<h2 class=sjh><a class="hlink h" data-go="${go}"><b>${t}</b>${SUB}</a></h2>`;
const FCI='<svg width=18 height=18 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><rect x=3 y=5 width=11 height=12 rx=2 /><path d="M7 3h8a2 2 0 0 1 2 2v9"/></svg>';
// Vectors already has Binny's button, so the list starts with the next ones
const WIN3=[['Algebra',7,1],['Trigonometry',5,1],['Mensuration',4,0]];
const win=`<div class=win4>${H2('Practice: Mathematics','More marks to win')}${WIN3.map(t=>`<div class=wrow2><a class=wmain data-go="Practice set: ${t[0]}"><span class=at><b>${t[0]}</b><span>Practise · 10 min</span></span><span class=wn>+${t[1]}<small> marks</small></span></a>${t[2]?`<a class=fc data-go="Flashcards: ${t[0]}" aria-label="${t[0]} flashcards">${FCI}</a>`:'<span class=fcx></span>'}</div>`).join('')}</div>`;
const papers=`<div class=win4>${H2('All Mathematics papers','Papers')}${[...PATH].reverse().map(p=>`<a class=rp data-go="Result: ${p[3]}"><b style="color:var(${GVV[p[1]]})">${p[1]}</b><span class=at><b>${p[3]}</b><span>${p[2]}/${OUT} · ${p[0]}</span></span>${CHEV}</a>`).join('')}</div>`;
const pathSec=`<section class=sec7>${H2('Mathematics progress','Your path to A*')}${steps()}</section>`;
const hd=`<div class=sjhd><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><div class=t><h1>Mathematics</h1><span class=s>0580 · Extended</span></div><a class=pill4 data-go="Study plan: exam dates">${CAL}188 days${SUB}</a></div>`;
const tabSub=TAB6('').replace('<a data-go="Subjects tab">','<a class=on aria-current=page data-go="Subjects tab">');
put('SB',`${hd}<div class=sjpad>${pathSec}<section class=tip2>${say()}</section>${win}<div class=sec7>${H2('Topic map','Topics')}${tmapP}</div>${papers}</div>${tabSub}`);
put('SBD',`${DRAIL6('Subjects')}<div class=dmain><header class=dtop><a class=icl data-go="Back to Subjects" aria-label=Back>${BACK}</a><h1>Mathematics</h1><a class=pill4 data-go="Study plan: exam dates">${CAL}188 days to Paper 4${SUB}</a></header><div class=sjd><section class=sjl>${pathSec}<section class=tip2>${say(72)}</section>${win}</section><section class=sjr><div class=sec7>${H2('Topic map','Topics')}${tmapD}</div>${papers}</section></div></div>`);
}
