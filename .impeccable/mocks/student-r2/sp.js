// Study plan · round 1. One week across subjects, subject filter, today first, bottom sheet per session.
{
const IC={
 practice:'<svg width=20 height=20 viewBox="0 0 22 22" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round aria-hidden=true><path d="M5 4h12v14H5zM8 8h6M8 12h6"/></svg>',
 cards:'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round aria-hidden=true><rect x=3 y=5 width=11 height=12 rx=2 /><path d="M7 3h8a2 2 0 0 1 2 2v9"/></svg>',
 paper:'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linejoin=round stroke-linecap=round aria-hidden=true><path d="M5 2.5h7l3.5 3.5v11.5h-10.5zM12 2.5V6h3.5M8 10h5M8 13h5"/></svg>',
 review:'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.7 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M3.5 10a6.5 6.5 0 1 0 2-4.7M3.5 3v3.5H7"/></svg>'};
const TK='<svg width=16 height=16 viewBox="0 0 16 16" fill=none stroke=currentColor stroke-width=2.2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M3.5 8.3 6.5 11l6-6.5"/></svg>';
const SUBC={Maths:'--gA',Physics:'oklch(.55 .1 250)','Add Maths':'oklch(.55 .1 300)'};
// [day, kind, label, topic, subject, minutes, why, state]
const S=[
 ['Mon','practice','Practice set','Algebra','Maths',10,'7 marks lost on Paper 4','done'],
 ['Tue','cards','Flashcards','Forces','Physics',5,'14 cards due','done'],
 ['Wed','practice','Practice set','Quadratic inequalities','Add Maths',10,'6 marks lost on Paper 1','missed'],
 ['Thu','practice','Practice set','Vectors','Maths',10,'Cost you 9 marks on Paper 4','today'],
 ['Thu','cards','Flashcards','Waves','Physics',5,'12 cards due today','today'],
 ['Thu','paper','Past paper','0625/42 · Physics','Physics',45,'Your last paper was 9 days ago','week'],
 ['Fri','practice','Practice set','Trigonometry','Maths',10,'5 marks lost on Paper 4',''],
 ['Sat','cards','Flashcards','Functions','Add Maths',5,'9 cards due',''],
 ['Sun','review','Review','Mistakes from this week','All',15,'Go over what you got wrong',''],
];
const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
const dot=s=>`<i class=sdot style="background:${SUBC[s]?.startsWith('--')?`var(${SUBC[s]})`:SUBC[s]||'var(--v)'}"></i>`;
const row=(r,big)=>`<a class="srow2${big?' big':''}${r[7]==='done'?' sdone':''}" data-go="Session sheet: ${r[3]}"><span class="sic ${r[1]}">${r[7]==='done'?TK:IC[r[1]]}</span><span class=at><b>${r[3]}</b><span>${dot(r[4])}${r[4]} · ${r[2]} · ${r[5]} min</span>${big?`<span class=why>${r[6]}</span>`:''}</span>${CHEV}</a>`;
const filt=on=>`<div class=sfilt role=tablist aria-label="Subject">${['All','Maths','Physics','Add Maths'].map(s=>`<button role=tab aria-selected=${s===on}>${s==='All'?'':dot(s)}${s}</button>`).join('')}</div>`;
const week=today=>`<div class=wk8>${DAYS.map(d=>{const ss=S.filter(r=>r[0]===d);const done=ss.length&&ss.every(r=>r[7]==='done');const miss=ss.some(r=>r[7]==='missed');return `<a class="${d===today?'now':''}${done?' ok':''}${miss?' miss':''}" data-go="Day: ${d}"><span>${d[0]}</span><i>${done?TK:ss.length}</i></a>`}).join('')}</div>`;
const hd=`<div class=sjhd><a class=icl data-go="Back to Home" aria-label=Back>${BACK}</a><div class=t><h1>This week</h1><span class=s>2 of 9 done · 1 h 55 min</span></div><a class=pill4 data-go="Exam dates">${CAL}188 days${SUB}</a></div>`;
const todayHead=`<div class=tdh><div class=tdr>${ring4([0,0,0])}<div><h2 class=sjh2>Today · Thursday</h2><span class=s2>2 sessions · 15 min</span></div></div></div>`;
const missed=`<a class=missr data-go="Session sheet: Quadratic inequalities"><span>Missed Wed · Quadratic inequalities</span><b>Move to today</b></a>`;
const later=`<div class=win4><h2 class=sjh2>Later this week</h2>${['Fri','Sat','Sun'].map(d=>`<div class=dgrp><span class=dl>${d}</span>${S.filter(r=>r[0]===d).map(r=>row(r)).join('')}</div>`).join('')}</div>`;
const doneSec=`<details class=dsec><summary>${TK} 2 done this week <span>Mon · Tue</span></summary>${S.filter(r=>r[7]==='done').map(r=>row(r)).join('')}</details>`;
const based=`<a class=based data-go="What this plan is based on">${IC.review.replace('width=20 height=20','width=16 height=16')} Built from your last 4 papers and weak topics · <b>Rebuild</b></a>`;

// WA: today first, week strip below
put('WA',`${hd}<div class=sjpad>${filt('All')}${todayHead}<div class=tdl>${S.filter(r=>r[7]==='today').map(r=>row(r,1)).join('')}</div>${missed}<div class=sec7><h2 class=sjh2>Any day this week</h2>${week('Thu')}${S.filter(r=>r[7]==='week').map(r=>row(r,1)).join('')}</div>${later}${doneSec}${based}</div>${TAB6('')}`);

// WB: Binny line on top, strip, then today
put('WB',`${hd}<div class=sjpad>${filt('All')}<div class=say2><div class=bwrap>${BIN('happy',58)}</div><p class=bub2>15 minutes today. Vectors first!</p></div>${week('Thu')}<div class=tdl>${S.filter(r=>r[7]==='today').map(r=>row(r,1)).join('')}</div>${missed}${later}${doneSec}${based}</div>${TAB6('')}`);

// WM: filtered to Maths = today's per-subject week (target grade, exam, based on)
const M=S.filter(r=>r[4]==='Maths');
put('WM',`${hd.replace('2 of 9 done · 1 h 55 min','Maths · 3 sessions · 30 min')}<div class=sjpad>${filt('Maths')}<div class=mtop><span><b style="color:var(--ga)">A*</b> target</span><span>Paper 4 in 188 days</span><span>7 marks to go</span></div>${todayHead.replace('2 sessions · 15 min','1 session · 10 min')}<div class=tdl>${row(M[1],1)}</div><div class=win4><h2 class=sjh2>Later this week</h2><div class=dgrp><span class=dl>Fri</span>${row(M[2])}</div></div><details class=dsec open><summary>${TK} 1 done <span>Mon</span></summary>${row(M[0])}</details><div class=sec7><h2 class=sjh2>Why these topics</h2><div class=tmap>${[['Vectors',41,'w'],['Algebra',58,'w'],['Trigonometry',62,'m']].map(t=>`<a class="tm ${t[2]}"><span>${t[0]}</span><b>${t[1]}%</b></a>`).join('')}</div><p class=hint2>Your weakest Maths topics from 4 papers.</p></div>${based}</div>${TAB6('')}`);

// SS: bottom sheet for a session
put('SS',`${hd}<div class="sjpad dimmed">${filt('All')}${todayHead}<div class=tdl>${S.filter(r=>r[7]==='today').map(r=>row(r,1)).join('')}</div></div><div class=scrim></div><div class="rvl leave ssh" role=dialog aria-label="Vectors session"><span class=grab aria-hidden=true></span><div class=shd><span class="sic practice">${IC.practice}</span><div><h2 class=sh2>Vectors</h2><span class=s2>${dot('Maths')}Maths · Practice set · 10 min</span></div></div><p class=whyb><b>Why this?</b> Vectors cost you 9 marks on your last Paper 4. It’s the quickest way to your A*.</p><button class="btn big4 go2">Start · +9 marks</button><div class=sacts><button class=sa>${TK} Mark done</button><button class=sa>${CAL} Move</button></div><div class=movd aria-label="Move to">${['Fri','Sat','Sun'].map((d,i)=>`<button class="${i===0?'on':''}">${d}</button>`).join('')}</div></div>`);

// Z0: no plan yet / not enough to plan from
put('Z0',`${hd.replace('2 of 9 done · 1 h 55 min','No plan yet')}<div class=sjpad><div class=err2 style="padding-top:20px"><div class=bwrap>${BIN('open',96)}</div><h2>Let’s plan your week</h2><p>Lemely builds it from your papers and weak topics. Takes a second.</p><button class="btn big4 go2">Build my week</button></div><ol class=walk2><li><span class=wn2>1</span><span class=at><b>Short sessions</b><span>10 minutes of practice, 5 of flashcards.</span></span></li><li><span class=wn2>2</span><span class=at><b>Weakest topics first</b><span>The ones that cost you the most marks.</span></span></li><li><span class=wn2>3</span><span class=at><b>Rebuilt each week</b><span>Every new paper sharpens the plan.</span></span></li></ol></div>${TAB6('')}`);
put('Z1',`${hd.replace('2 of 9 done · 1 h 55 min','No plan yet')}<div class=sjpad><div class=err2 style="padding-top:20px"><div class=bwrap>${BIN('thinking',96)}</div><h2>I need a paper first</h2><p>Mark one past paper, or take the 10-minute placement test, and I’ll plan your week.</p><button class="btn big4 go2">Scan a paper</button><a class="lnk q" data-go="Placement test">Take the placement test</a></div></div>${TAB6('')}`);

// desktop: week as 7 columns, today highlighted, sheet becomes side panel
put('SD',`${DRAIL6('Home')}<div class=dmain><header class=dtop><a class=icl aria-label=Back>${BACK}</a><div class=t2><h1>This week</h1><span class=s>2 of 9 done · 1 h 55 min</span></div>${filt('All')}<a class=pill4>${CAL}188 days to Paper 4${SUB}</a></header><div class=spd><div class=spl>${todayHead}<div class=tdl>${S.filter(r=>r[7]==='today').map(r=>row(r,1)).join('')}</div>${missed}<div class=sec7><h2 class=sjh2>Any day this week</h2>${week('Thu')}${S.filter(r=>r[7]==='week').map(r=>row(r,1)).join('')}</div>${later}${doneSec}</div><aside class=sside><div class=shd><span class="sic practice">${IC.practice}</span><div><h2 class=sh2>Vectors</h2><span class=s2>${dot('Maths')}Maths · Practice set · 10 min</span></div></div><p class=whyb><b>Why this?</b> Vectors cost you 9 marks on your last Paper 4. It’s the quickest way to your A*.</p><button class="btn big4 go2">Start · +9 marks</button><div class=sacts><button class=sa>${TK} Mark done</button><button class=sa>${CAL} Move</button></div><div class=say2 style="margin-top:auto"><div class=bwrap>${BIN('happy',56)}</div><p class=bub2>15 minutes today!</p></div></aside></div>${based.replace('class=based','class="based d"')}</div>`);

// ---------- polish: states carried over from the live week + session screens ----------
const shell=b=>`${hd}<div class=sjpad>${b}</div>${TAB6('')}`;
put('PL',shell(`<div class=sk2c aria-busy=true aria-label="Loading your week"><span class=sk style="height:40px;border-radius:12px"></span><span class=sk style="width:180px;height:24px"></span>${'<span class=sk style="height:64px;border-radius:14px"></span>'.repeat(2)}<span class=sk style="height:56px;border-radius:14px"></span>${'<span class=sk style="height:52px;border-radius:14px"></span>'.repeat(3)}</div>`));
put('PE',shell(`<div class=err2><div class=bwrap>${BIN('sad',96)}</div><h2>We couldn’t load your week</h2><p>Check your connection, then try again.</p><button class="btn big4 go2">Try again</button><a class="lnk q" data-go="Back to Home">Back to Home</a></div>`));
put('PD',`${hd.replace('2 of 9 done · 1 h 55 min','9 of 9 done · 1 h 55 min')}<div class=sjpad>${filt('All')}<div class=err2 style="padding-top:12px"><div class=bwrap>${BIN('happy',110)}</div><h2>Week done!</h2><p>All 9 sessions, 1 h 55 min. Vectors and Waves moved up.</p><div class=gain3 style="width:100%"><span class=g3><b>+21</b><small>marks back</small></span><span class=g3><b>+260</b><small>XP</small></span><span class=g3><b>7</b><small>days in a row</small></span></div><button class="btn big4 go2">Plan next week</button><a class="lnk q" data-go="Bonus practice">Bonus practice</a></div></div>${TAB6('')}`);
put('PR',`${hd}<div class=sjpad>${filt('All')}<div class=rebuild role=status><div class=bwrap>${BIN('thinking',52)}</div><p><b>Rebuilding your week…</b><br><span>Using your new Physics paper.</span></p></div><div class=dimmed>${todayHead}<div class=tdl>${S.filter(r=>r[7]==='today').map(r=>row(r,1)).join('')}</div></div></div>${TAB6('')}`);
put('PX',`${hd}<div class="sjpad dimmed">${filt('All')}${todayHead}</div><div class=scrim></div><div class="rvl leave ssh" role=dialog aria-label="Vectors session"><span class=grab aria-hidden=true></span><div class=shd><span class="sic practice">${IC.practice}</span><div><h2 class=sh2>Vectors</h2><span class=s2>${dot('Maths')}Maths · Practice set · 10 min</span></div></div><div class=errl role=alert>Couldn’t mark this done. Check your connection and try again.</div><button class="btn big4 go2">Start · +9 marks</button><div class=sacts><button class=sa>${TK} Try again</button><button class=sa>${CAL} Move</button></div></div>`);
}
