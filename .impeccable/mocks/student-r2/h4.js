// H4 · calm stage. One action (Binny's), quiet Today line, grade floor, at most two moment-picked rows.
const M4={
 morning:{mood:'open',say:'Morning, Mariam. Vectors cost you 9 marks last time. Ten minutes fixes most of it.',go:'Start 10 minutes',goal:[0,0,0],streak:0,also:['teacher','scan']},
 paper:{mood:'happy',say:'61 out of 80. That’s a B, up from a C! Q8 is the one to fix.',go:'Fix Q8',goal:[0,0,1],streak:0,also:['result']},
 tough:{mood:'sad',say:'Tough one. Let’s win back the easy marks first, one question at a time.',go:'Start with Q3',goal:[0,0,1],streak:0,also:['resultD']},
 streak:{mood:'thinking',say:'Your 9-day streak ends at midnight. One quick set keeps it going.',go:'Keep my streak',goal:[0,1,1],streak:0,also:[]},
 done:{mood:'happy',say:'Three for three today. Go enjoy your evening.',go:'Bonus flashcards',goal:[1,1,1],streak:1,also:['up']},
 back:{mood:'wink',say:'There you are! Six days off is fine. Ease back in with five minutes.',go:'5-minute warm-up',goal:[0,0,0],streak:0,also:[]},
 marking:{mood:'thinking',say:'Marking your Physics paper. 8 of 14 questions done.',go:'Watch it mark',goal:[1,0,1],streak:0,also:[]},
};
const ALSO={
 teacher:`<a class=arow><span class=tav2>MH</span><span class=at><b>Ms. Hanna replied to your challenge</b><span>Q7 · she added a mark</span></span>${CHEV}</a>`,
 scan:`<a class=arow><span class=aic>${CAM.replace('width=26 height=26','width=20 height=20')}</span><span class=at><b>Scan your next paper</b><span>Your last one was 9 days ago</span></span>${CHEV}</a>`,
 result:`<a class=arow><span class=aic g style="color:var(--gB)">B</span><span class=at><b>See your full result</b><span>Mathematics · Paper 4</span></span>${CHEV}</a>`,
 resultD:`<a class=arow><span class=aic g style="color:var(--gD);background:oklch(.95 .035 62)">D</span><span class=at><b>See your full result</b><span>Physics · Paper 4 · 3 easy marks to win back</span></span>${CHEV}</a>`,
 up:`<a class=arow><span class=aic>${'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M4 13l4-4 3 3 5-6M12 6h4v4"/></svg>'}</span><span class=at><b>You moved up to 3rd in 10B</b><span>This week</span></span>${CHEV}</a>`,
};
const ring4=g=>{const segs=[0,1,2].map(i=>`<circle r=13 cx=16 cy=16 fill=none stroke="${g[i]?'var(--gold)':'oklch(.9 .012 240)'}" stroke-width=4.5 stroke-dasharray="23 59" stroke-dashoffset="${-i*27.2}" stroke-linecap=round transform="rotate(-90 16 16)"/>`).join('');return `<svg width=32 height=32 viewBox="0 0 32 32" aria-hidden=true>${segs}</svg>`};
const GL=['Practice','Flashcards','A paper this week'];
const todayLine=g=>`<div class=tline aria-label="Today: ${g.filter(Boolean).length} of 3 done">${ring4(g)}<span class=tl1>${g.filter(Boolean).length} of 3 today</span><span class=tl2>${GL.map((n,i)=>`<i class="${g[i]?'ok':''}">${n}</i>`).join('')}</span></div>`;
const floor=`<div class=floor>${SUBS.map(s=>`<a class=fg><b style="color:var(${GV[s.g]})">${s.g}</b><span class=fn2>${s.n.replace('Additional Maths','Add Maths')}</span><span class=fs>${s.gap} pts to ${s.next}</span></a>`).join('')}</div>`;
const WIN=`<div class=win4><h3 class=h3>Win marks back</h3>${[['Vectors','Mathematics',9],['Waves','Physics',7],['Quadratic inequalities','Add Maths',6]].map(t=>`<a class=wrow><span class=at><b>${t[0]}</b><span>${t[1]}</span></span><span class=wn>+${t[2]}<small> marks</small></span>${CHEV}</a>`).join('')}</div>`;
const top4=m=>`<div class=top4><span class="pill4${m.streak?' lit':''}">${FLAME}9 days</span><span class=pill4>${'<svg width=14 height=14 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.8 aria-hidden=true><rect x=3 y=4.5 width=14 height=12 rx=2.5 /><path d="M3 8.5h14M7 2.5v4M13 2.5v4"/></svg>'}180 days to exams</span></div>`;
function H4(k){const m=M4[k];return `<div class=h4pad>${top4(m)}<div class=stage4><div class=spot aria-hidden=true></div><div class=bwrap>${BIN(m.mood,150)}</div><p class=line4>${m.say}</p><div class=go4><button class="btn big4">${m.go}</button><button class="lnk q">Not now</button></div></div>${todayLine(m.goal)}${floor}${WIN}${m.also.length?`<div class=also>${m.also.map(a=>ALSO[a]).join('')}</div>`:''}</div>${TABBAR}`}
function H4D(k){const m=M4[k];return `${SRAIL('Overview')}<div class=main><div class=hd style="padding-bottom:0"><div class=t><h1>Hi, Mariam</h1></div>${top4(m)}<button class="btn tide">${CAM.replace('width=26 height=26','width=18 height=18')} Scan a paper</button></div><div class=d4><div class=stage4 d><div class=spot aria-hidden=true></div><div class=bwrap>${BIN(m.mood,190)}</div><p class=line4>${m.say}</p><div class=go4><button class="btn big4">${m.go}</button><button class="lnk q">Not now</button></div></div><div class=d4r>${todayLine(m.goal)}${floor}${WIN}${m.also.length?`<div class=also>${m.also.map(a=>ALSO[a]).join('')}</div>`:''}</div></div></div>`}
function paint4(k){document.querySelectorAll('[data-m4]').forEach(b=>b.classList.toggle('on',b.dataset.m4===k));put('P4a',H4(k));put('D4',H4D(k))}
put('P4m',H4('morning'));put('P4p',H4('paper'));put('P4t',H4('tough'));put('P4d',H4('done'));
document.addEventListener('click',e=>{const b=e.target.closest('[data-m4]');if(b)paint4(b.dataset.m4)});
paint4('back');
