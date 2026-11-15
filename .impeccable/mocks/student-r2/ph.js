// Practice tab hub · round 1. Mode grid first, homework on top when set, win-marks-back topics, recent runs, past papers, set builder.
{
const IC={
 set:'<svg width=22 height=22 viewBox="0 0 22 22" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M5 4h12v14H5zM8 8h6M8 12h4"/><path d="m12.5 15 1.5 1.5 3-3.5"/></svg>',
 cards:'<svg width=22 height=22 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><rect x=3 y=5 width=11 height=12 rx=2 /><path d="M7 3h8a2 2 0 0 1 2 2v9"/></svg>',
 paper:'<svg width=22 height=22 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round stroke-linecap=round aria-hidden=true><path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5"/></svg>',
 test:'<svg width=22 height=22 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linecap=round stroke-linejoin=round aria-hidden=true><circle cx=10 cy=10 r=7 /><path d="m12.8 7.2-1.8 3.8-3.8 1.8 1.8-3.8z"/></svg>',
 resume:'<svg width=18 height=18 viewBox="0 0 18 18" fill=currentColor aria-hidden=true><path d="M6 4.2v9.6L13.5 9z"/></svg>',
 hw:'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M3 7.5 10 4l7 3.5-7 3.5z"/><path d="M6 9.2V13c0 1 1.8 2.2 4 2.2s4-1.2 4-2.2V9.2"/></svg>',
 print:'<svg width=18 height=18 viewBox="0 0 18 18" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><path d="M5 7V2.5h8V7M5 13H3V7h12v6h-2M5 10.5h8v5H5z"/></svg>',
 clock:'<svg width=18 height=18 viewBox="0 0 18 18" fill=none stroke=currentColor stroke-width=1.7 stroke-linecap=round aria-hidden=true><circle cx=9 cy=9.5 r=6 /><path d="M9 6.5v3l2 1.5M7 2h4"/></svg>'};
const TK='<svg width=16 height=16 viewBox="0 0 16 16" fill=none stroke=currentColor stroke-width=2.2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M3.5 8.3 6.5 11l6-6.5"/></svg>';
const SUBC={Maths:'var(--gA)',Physics:'oklch(.55 .1 250)','Add Maths':'oklch(.55 .1 300)'};
const dot=s=>`<i class=sdot style="background:${SUBC[s]}"></i>`;
const tabOn=TAB6('').replace('<a data-go="Practice tab">','<a class=on aria-current=page data-go="Practice tab">');
const hd=(s='')=>`<div class="sjhd root"><div class=t><h1>Practice</h1>${s?`<span class=s>${s}</span>`:''}</div></div>`;
const hw=`<a class=hwr data-go="Homework: Vectors set"><span class="sic hw">${IC.hw}</span><span class=at><b>Homework · Vectors set</b><span>Ms Adel · 8 questions · due Friday</span></span>${CHEV}</a>`;
// [key, icon, title, status, cls]
const T=[['set','set','Practice set','Build your own · 10 min','pset'],['cards','cards','Flashcards','<b>26</b> due today','pcard'],['paper','paper','Past papers','Print or do timed','ppap'],['test','test','Placement test','Find your level · 10 min','ptest']];
const tile=t=>`<a class="ptile ${t[4]}" data-go="${t[2]}"><span class=pti>${IC[t[1]]}</span><b>${t[2]}</b><span>${t[3]}</span></a>`;
const W=[['Vectors','Maths',9],['Waves','Physics',6],['Quadratic inequalities','Add Maths',6]];
const win=`<div class=win4><div class=h2row><h2 class=sjh2>Win marks back</h2><a class=lnk data-go="All topics">All topics</a></div>${W.map(w=>`<a class=wmr data-go="Practice: ${w[0]}"><span class=at><b>${w[0]}</b><span>${dot(w[1])}${w[1]}</span></span><span class=plus>+${w[2]}<small>marks</small></span>${CHEV}</a>`).join('')}</div>`;
const R=[['Vectors','Maths','7 of 9 back','Tue'],['Algebra','Maths','5 of 6 back','Mon'],['Forces','Physics','3 of 8 back','Sun']];
const recent=`<div class=win4><div class=h2row><h2 class=sjh2>Recent</h2><a class=lnk data-go="All practice">See all</a></div><a class="wmr res" data-go="Resume: Trigonometry"><span class="sic go">${IC.resume}</span><span class=at><b>Trigonometry</b><span>${dot('Maths')}Question 4 of 8 · saved</span></span><span class=rsm>Resume</span></a>${R.map(r=>`<a class=wmr data-go="Result: ${r[0]}"><span class="sic ok">${TK}</span><span class=at><b>${r[0]}</b><span>${dot(r[1])}${r[2]} · ${r[3]}</span></span>${CHEV}</a>`).join('')}</div>`;

// A: plain 2x2 grid
put('PA',`${hd('3 topics to win back')}<div class=sjpad>${hw}<div class=pgrid>${T.map(tile).join('')}</div>${win}${recent}</div>${tabOn}`);

// B: big Practice set tile with Binny, three below (no homework set)
put('PB',`${hd('3 topics to win back')}<div class=sjpad><a class="ptile pset big" data-go="Practice set"><div class=bwrap>${BIN('happy',72)}</div><span class=at><b>Practice set</b><span>Vectors is worth <em>+9 marks</em></span></span><span class="btn sm">Start</span></a><div class="pgrid three">${T.slice(1).map(tile).join('')}</div>${win}${recent}</div>${tabOn}`);

// C: tinted tiles, big glyphs, homework badge on the set tile
put('PC',`${hd('3 topics to win back')}<div class=sjpad>${hw}<div class="pgrid tint">${T.map(t=>tile(t).replace('<span class=pti>','<span class=pti aria-hidden=true>')).join('')}</div>${win}${recent}</div>${tabOn}`);

// set builder sheet (live PracticeGenerator: subject, topics, weak only, count, difficulty, source, availability, start/print)
const TOP=[['Vectors',1,1],['Algebra',1,0],['Trigonometry',1,0],['Probability',0,0],['Sequences',0,0],['Circle theorems',0,0]];
put('PS',`${hd()}<div class="sjpad dimmed"><div class=pgrid>${T.map(tile).join('')}</div></div><div class=scrim></div><div class="rvl leave ssh" role=dialog aria-label="Practice set"><span class=grab aria-hidden=true></span><h2 class=sh2>Practice set</h2><div class=sfilt role=tablist aria-label=Subject>${['Maths','Physics','Add Maths'].map((s,i)=>`<button role=tab aria-selected=${!i}>${dot(s)}${s}</button>`).join('')}</div><div class=wtog><span>Weak topics only</span><span class="sw on" role=switch aria-checked=true></span></div><div class=tmap>${TOP.filter(t=>t[1]).map(t=>`<button class="tm w${t[2]?' sel':''}" aria-pressed=${!!t[2]}><span>${t[0]}</span></button>`).join('')}</div><div class=cnt><span>Questions</span><div class=stepr><button aria-label=Fewer>−</button><span class=val>10</span><button aria-label=More>+</button></div></div><details class=more><summary>Difficulty and source</summary></details><p class=avl role=status>${TK} 32 questions match</p><button class="btn big4 go2">Start now</button><button class="lnk q tc">${IC.print} Print instead</button></div>`);

// past papers
const PP=[['0580/42','May/June 2025','Paper 4 · 2 h 30','52/80'],['0580/41','Oct/Nov 2024','Paper 4 · 2 h 30',''],['0580/22','May/June 2025','Paper 2 · 1 h 30','41/70'],['0580/21','Oct/Nov 2024','Paper 2 · 1 h 30','']];
const pdr=p=>`<a class=ppr data-go="Paper: ${p[0]}"><span class="sic ${p[3]?'ok':'pp'}">${p[3]?TK:IC.paper}</span><span class=at><b>${p[0]} · ${p[1]}</b><span>${p[2]}</span></span><span class=psc>${p[3]}</span>${CHEV}</a>`;
put('PP',`<div class=sjhd><a class=icl data-go=Back aria-label=Back>${BACK}</a><div class=t><h1>Past papers</h1><span class=s>Cambridge IGCSE</span></div></div><div class=sjpad><div class=sfilt role=tablist aria-label=Subject>${['Maths','Physics','Add Maths'].map((s,i)=>`<button role=tab aria-selected=${!i}>${dot(s)}${s}</button>`).join('')}</div><div class=win4><h2 class=sjh2>Paper 4</h2>${PP.filter(p=>p[2].startsWith('Paper 4')).map(pdr).join('')}</div><div class=win4><h2 class=sjh2>Paper 2</h2>${PP.filter(p=>p[2].startsWith('Paper 2')).map(pdr).join('')}</div></div>${tabOn}`);
put('PQ',`<div class=sjhd><a class=icl data-go=Back aria-label=Back>${BACK}</a><div class=t><h1>Past papers</h1><span class=s>Cambridge IGCSE</span></div></div><div class="sjpad dimmed"><div class=win4>${PP.map(pdr).join('')}</div></div><div class=scrim></div><div class="rvl leave ssh" role=dialog aria-label="0580/41"><span class=grab aria-hidden=true></span><div class=shd><span class="sic pp">${IC.paper}</span><div><h2 class=sh2>0580/41 · Oct/Nov 2024</h2><span class=s2>${dot('Maths')}Maths · Paper 4 · 80 marks</span></div></div><div class=ppopt><button class=on><span class=pti>${IC.clock}</span><span class=at><b>Do it timed</b><span>2 h 30 on paper, then scan it</span></span></button><button><span class=pti>${IC.print}</span><span class=at><b>Just print it</b><span>No timer. Scan it when you’re done.</span></span></button></div><button class="btn big4 go2">Print paper</button><p class=hint2>Lemely marks it when you scan your answers.</p></div>`);

// first time: no papers marked yet
put('PZ',`${hd()}<div class=sjpad><div class=pgrid>${T.map(t=>tile(t).replace('<b>26</b> due today','Make your first deck').replace('Build your own · 10 min','Pick any topic')).join('')}</div><div class=say2><div class=bwrap>${BIN('open',64)}</div><p class=bub2>Scan a paper and I’ll find your marks to win back.</p></div><ol class=walk2><li><span class=wn2>1</span><span class=at><b>Scan a marked paper</b><span>Or take the 10-minute placement test.</span></span></li><li><span class=wn2>2</span><span class=at><b>See where marks went</b><span>Your weakest topics show up here.</span></span></li><li><span class=wn2>3</span><span class=at><b>Win them back</b><span>Short sets, checked as you go.</span></span></li></ol><button class="btn big4 go2">Scan a paper</button></div>${tabOn}`);

// ---------- final (C): Binny line, sparse, builder states, loading/error, desktop ----------
const gridC=(f=t=>t)=>`<div class="pgrid tint">${T.map(t=>tile(f(t)).replace('<span class=pti>','<span class=pti aria-hidden=true>')).join('')}</div>`;
const say=t=>`<div class="say2 sm"><div class=bwrap>${BIN('happy',48)}</div><p class=bub2>${t}</p></div>`;
put('CF',`${hd('3 topics to win back')}<div class=sjpad>${hw}${gridC()}${say('Vectors first. +9 marks!')}${win}${recent}</div>${tabOn}`);
put('CN',`${hd('3 topics to win back')}<div class=sjpad>${gridC()}${say('Vectors first. +9 marks!')}${win}${recent}</div>${tabOn}`);
put('CZ',`${hd()}<div class=sjpad>${gridC(t=>t.map(v=>v==='<b>26</b> due today'?'Make your first deck':v==='Build your own · 10 min'?'Pick any topic':v))}<div class=say2><div class=bwrap>${BIN('open',64)}</div><p class=bub2>Scan a paper and I’ll find your marks to win back.</p></div><ol class=walk2><li><span class=wn2>1</span><span class=at><b>Scan a marked paper</b><span>Or take the 10-minute placement test.</span></span></li><li><span class=wn2>2</span><span class=at><b>See where marks went</b><span>Your weakest topics show up here.</span></span></li><li><span class=wn2>3</span><span class=at><b>Win them back</b><span>Short sets, checked as you go.</span></span></li></ol><button class="btn big4 go2">Scan a paper</button></div>${tabOn}`);
// sparse: one paper marked, one topic, nothing done yet
put('CS',`${hd('1 topic to win back')}<div class=sjpad>${gridC(t=>t.map(v=>v==='<b>26</b> due today'?'Make your first deck':v))}${say('Good start! Try one set.')}<div class=win4><h2 class=sjh2>Win marks back</h2><a class=wmr data-go="Practice: Vectors"><span class=at><b>Vectors</b><span>${dot('Maths')}Maths</span></span><span class=plus>+9<small>marks</small></span>${CHEV}</a></div><div class=tipr><span class=at><b>More papers, sharper picks</b><span>Each paper you scan adds topics here.</span></span><button class="btn sm">Scan</button></div></div>${tabOn}`);
const sh=b=>`${hd()}<div class=sjpad>${b}</div>${tabOn}`;
put('CL',sh(`<div class=sk2c aria-busy=true aria-label="Loading practice"><div class=pgrid>${'<span class=sk style="height:124px;border-radius:20px"></span>'.repeat(4)}</div><span class=sk style="width:160px;height:22px"></span>${'<span class=sk style="height:52px;border-radius:14px"></span>'.repeat(3)}</div>`));
put('CE',sh(`${gridC()}<div class=err2 style="padding-top:8px"><div class=bwrap>${BIN('sad',80)}</div><h2>We couldn’t load your topics</h2><p>The tiles still work. Check your connection for the rest.</p><button class="btn big4 go2">Try again</button></div>`));
// builder sheet states (live: checking, no match, no topics for subject, couldn't create)
const bsheet=(subj,body,cta='Start now',dis=false)=>`${hd()}<div class="sjpad dimmed">${gridC()}</div><div class=scrim></div><div class="rvl leave ssh" role=dialog aria-label="Practice set"><span class=grab aria-hidden=true></span><h2 class=sh2>Practice set</h2><div class=sfilt role=tablist aria-label=Subject>${['Maths','Physics','Add Maths'].map(s=>`<button role=tab aria-selected=${s===subj}>${dot(s)}${s}</button>`).join('')}</div>${body}<button class="btn big4 go2"${dis?' disabled aria-disabled=true':''}>${cta}</button>${dis?'':`<button class="lnk q tc">${IC.print} Print instead</button>`}</div>`;
const topics=sel=>`<div class=wtog><span>Weak topics only</span><span class="sw${sel?' on':''}" role=switch aria-checked=${!!sel}></span></div><div class=tmap>${TOP.filter(t=>sel?t[1]:1).slice(0,5).map(t=>`<button class="tm w${t[0]==='Vectors'?' sel':''}" aria-pressed=${t[0]==='Vectors'}><span>${t[0]}</span></button>`).join('')}</div><div class=cnt><span>Questions</span><div class=stepr><button aria-label=Fewer>−</button><span class=val>10</span><button aria-label=More>+</button></div></div>`;
put('PS',bsheet('Maths',`${topics(1)}<details class=more><summary>Difficulty and source</summary></details><p class=avl role=status>${TK} 32 questions match</p>`));
put('CB1',bsheet('Maths',`${topics(1)}<p class="avl wait" role=status><span class=spin aria-hidden=true></span>Checking what matches…</p>`));
put('CB2',bsheet('Maths',`${topics(1).replace('<span class=val>10</span>','<span class=val>20</span>')}<p class="avl no" role=status>Only 6 questions match. Add a topic or ask for fewer.</p>`,'Start with 6'));
put('CB3',bsheet('Add Maths',`<div class=err2 style="padding:8px 0"><h2>No Add Maths questions yet</h2><p>We’re adding them. Try Maths or Physics for now.</p></div>`,'Start now',true));
put('CB4',bsheet('Maths',`<div class=errl role=alert>Couldn’t make this set. Try again.</div>${topics(1)}`,'Try again'));

// desktop C
put('CDK',`${DRAIL6('Practice')}<div class=dmain><header class=dtop><div class=t2><h1>Practice</h1><span class=s>3 topics to win back</span></div></header><div class=phd><div class=phr>${hw}${say('Vectors first. +9 marks!')}</div>${gridC().replace('pgrid tint','pgrid tint four')}<div class=pcols>${win}${recent}</div></div></div>`);

// desktop
put('PDK',`${DRAIL6('Practice')}<div class=dmain><header class=dtop><div class=t2><h1>Practice</h1><span class=s>3 topics to win back</span></div></header><div class=phd>${hw}<div class="pgrid four">${T.map(tile).join('')}</div><div class=pcols>${win}${recent}</div></div></div>`);
}
