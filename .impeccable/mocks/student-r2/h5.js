// H5: H4 locked layout + every element is a door. data-go names the destination (shown by the map toggle).
const BELL=`<button class=bell aria-label="Notifications, 2 unread" data-go="Notifications">${'<svg width=20 height=20 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M5 8a5 5 0 0 1 10 0c0 4 1.5 5.5 1.5 5.5h-13S5 12 5 8ZM8.5 16.5a1.6 1.6 0 0 0 3 0"/></svg>'}<i></i></button>`;
const SUB='<svg width=14 height=14 viewBox="0 0 16 16" fill=none stroke=currentColor stroke-width=2 stroke-linecap=round stroke-linejoin=round aria-hidden=true><path d="M6 3.5 10.5 8 6 12.5"/></svg>';
const go=(lbl,html)=>html.replace(/^<(\w+)/,`<$1 data-go="${lbl}"`);
function H5(k){const m=M4[k];
 const top=`<div class=top4><a class="pill4${m.streak?' lit':''}" data-go="Progress: streak, XP, level">${FLAME}9 days</a><a class=pill4 data-go="Study plan: exam dates">${'<svg width=14 height=14 viewBox="0 0 20 20" fill=none stroke=currentColor stroke-width=1.8 aria-hidden=true><rect x=3 y=4.5 width=14 height=12 rx=2.5 /><path d="M3 8.5h14M7 2.5v4M13 2.5v4"/></svg>'}180 days to exams</a><span style="flex:1"></span>${BELL}</div>`;
 const dest={morning:'Practice set: Vectors',paper:'Result, opened at Q8',tough:'Practice: easy marks, Q3',streak:'Quick practice set',done:'Flashcard review',back:'5-minute warm-up set',marking:'Marking progress'}[k];
 const stage=`<div class=stage4><div class=spot aria-hidden=true></div><div class=bwrap>${BIN(m.mood,150)}</div><p class=line4>${m.say}</p><div class=go4><button class="btn big4" data-go="${dest}">${m.go}</button><button class="lnk q">Not now</button></div></div>`;
 const g=m.goal;const today=`<div class=tline2><a class=hlink data-go="Study plan: this week">${ring4(g)}<b>${g.filter(Boolean).length} of 3 today</b>${SUB}</a><div class=tl3>${[['Practice','Practice set'],['Flashcards','Flashcard review'],['Paper this week','Scan']].map((n,i)=>`<a class="${g[i]?'ok':''}" data-go="${n[1]}">${n[0]}</a>`).join('')}</div></div>`;
 const fl=`<div class=floor>${SUBS.map(s=>`<a class=fg data-go="${s.n} page"><b style="color:var(${GV[s.g]})">${s.g}</b><span class=fn2>${s.n.replace('Additional Maths','Add Maths')}</span><span class=fs>${s.gap} pts to ${s.next}</span></a>`).join('')}</div>`;
 const win=`<div class=win4><a class="hlink h" data-go="Practice: all topics"><b>Win marks back</b>${SUB}</a>${[['Vectors','Mathematics',9],['Waves','Physics',7],['Quadratic inequalities','Add Maths',6]].map(t=>`<a class=wrow data-go="Practice set: ${t[0]}"><span class=at><b>${t[0]}</b><span>${t[1]}</span></span><span class=wn>+${t[2]}<small> marks</small></span>${CHEV}</a>`).join('')}</div>`;
 const alsoD={teacher:'Class thread: your challenge',scan:'Scan',result:'Result: Mathematics P4',resultD:'Result: Physics P4',up:'Standings'};
 const also=m.also.length?`<div class=also>${m.also.map(a=>ALSO[a].replace('<a class=arow',`<a class=arow data-go="${alsoD[a]}"`)).join('')}</div>`:'';
 return `<div class=h4pad>${top}${stage}${today}${fl}${win}${also}</div>${TABBAR.replace('<a class=on>','<a class=on data-go="Home">').replace(/<a><svg[^]*?<span>Practice<\/span><\/a>/,m=>m.replace('<a>','<a data-go="Practice tab">')).replace('<button class=scanc','<button data-go="Scan" class=scanc').replace(/<a>(<svg[^]*?<span>Subjects<\/span>)/,'<a data-go="Subjects tab">$1').replace(/<a>(<span class=avm)/,'<a data-go="Me">$1')}`}
const ME=`<div class=abar><div class=t><h2>Me</h2><span class=s>Mariam · IGCSE · 3 subjects</span></div></div><div class=mepad>
<a class=mehead data-go="Progress"><span class=avm style="width:52px;height:52px;font-size:18px">M</span><div style="flex:1"><b>Level 7</b><span class=lb style="display:block;margin:6px 0 4px"><i style="width:48%"></i></span><span class=s>240 / 500 XP · 9-day streak</span></div>${CHEV}</a>
<div class=megroup><span class=mgl>Your people</span>${[['Classes','10B Mathematics · 10B Physics'],['Standings','3rd in 10B this week'],['Friends','4 friends'],['Parents','1 linked']].map(r=>`<a class=mrow data-go="${r[0]}"><b>${r[0]}</b><span>${r[1]}</span>${CHEV}</a>`).join('')}</div>
<div class=megroup><span class=mgl>Extra help</span>${[['Tutoring','Book a session with a tutor'],['Placement test','Find your starting level']].map(r=>`<a class=mrow data-go="${r[0]}"><b>${r[0]}</b><span>${r[1]}</span>${CHEV}</a>`).join('')}</div>
<div class=megroup><span class=mgl>Account</span>${[['Profile and settings',''],['Notifications',''],['Recently deleted','2 papers']].map(r=>`<a class=mrow data-go="${r[0]}"><b>${r[0]}</b><span>${r[1]}</span>${CHEV}</a>`).join('')}</div></div>${TABBAR.replace('<a class=on>','<a>').replace(/<a>(<span class=avm)/,'<a class=on>$1')}`;
function paint5(k){document.querySelectorAll('[data-m5]').forEach(b=>b.classList.toggle('on',b.dataset.m5===k));put('P5',H5(k));put('P5b',H5(k==='morning'?'paper':'morning'))}
put('ME',ME);
document.addEventListener('click',e=>{const b=e.target.closest('[data-m5]');if(b)paint5(b.dataset.m5);if(e.target.closest('#maptog'))document.body.classList.toggle('map')});
paint5('morning');
// Me v2: personal and alive, settings last
const ICO={
 classes:'<path d="M3 8.5 11 4.5l8 4-8 4z"/><path d="M6.5 10.5v4c1.2 1.3 2.8 2 4.5 2s3.3-.7 4.5-2v-4"/>',
 stand:'<path d="M4 18v-5h4v5M9 18V8h4v10M14 18v-7h4v7"/>',
 friends:'<circle cx=8 cy=8 r=3 /><circle cx=15 cy=9 r=2.5 /><path d="M3 17c.6-2.8 2.6-4 5-4s4.4 1.2 5 4M13.5 13.6c2 .1 3.6 1.2 4.1 3.4"/>',
 parents:'<path d="M11 18s-6.5-3.8-6.5-8.3A3.6 3.6 0 0 1 11 7.6a3.6 3.6 0 0 1 6.5 2.1C17.5 14.2 11 18 11 18Z"/>',
};
const ic=(k)=>`<svg width=24 height=24 viewBox="0 0 22 22" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true>${ICO[k]}</svg>`;
const BADGES=[['First paper',1,'<path d="M6 3.5h7l3 3v12H6z"/><path d="M8.5 12l2 2 3.5-4"/>'],['7-day streak',1,'<path d="M11 3c.6 3.4 5 5 5 10a5 5 0 0 1-10 0c0-2.2 1.1-3.6 2.2-4.4.2 1.8 1.1 2.6 2.2 2.9C10 9 10.5 5.8 11 3Z"/>'],['Grade up',1,'<path d="M5 15l4-4 3 3 5-6M13 8h4v4"/>'],['30-day streak',0,'<circle cx=11 cy=11 r=7 /><path d="M11 7v4l3 2"/>'],['A* paper',0,'<path d="M11 3.5l2.3 4.8 5.2.7-3.8 3.6.9 5.1L11 15.3l-4.6 2.4.9-5.1L3.5 9l5.2-.7z"/>']];
const ringLv=`<svg width=92 height=92 viewBox="0 0 92 92" aria-hidden=true><circle cx=46 cy=46 r=42 fill=none stroke="oklch(.92 .012 240)" stroke-width=6 /><circle cx=46 cy=46 r=42 fill=none stroke="var(--gold)" stroke-width=6 stroke-linecap=round stroke-dasharray="${0.48*264} 264" transform="rotate(-90 46 46)"/></svg>`;
const ME2=`<div class=mepad2>
<div class=mhero><a class=mav data-go="Profile">${ringLv}<span>M</span><b class=lvb>7</b></a><div style="flex:1;min-width:0"><h2>Mariam</h2><span class=s>Level 7 · 260 XP to level 8</span></div><div class=bpeek>${BIN('wink',66)}</div><button class=bell style="position:absolute;top:0;right:0;display:none"></button></div>
<a class=strk data-go="Progress: streak history"><div class=sd>${Array.from({length:14},(_,i)=>`<i class="${i>4?'on':''}${i===13?' now':''}"></i>`).join('')}</div><span><b>${FLAME} 9-day streak</b> best 14</span></a>
<div class=stats3><a data-go="All papers"><b>22</b><span>papers marked</span></a><a data-go="Practice history"><b>+64</b><span>marks won back</span></a><a data-go="Mathematics page"><b style="color:var(--gA)">A</b><span>best grade</span></a></div>
<div class=bdg><a class="hlink h" data-go="All badges"><b>Badges</b>${SUB}</a><div class=brow>${BADGES.map(b=>`<span class="bd${b[1]?' on':''}" title="${b[0]}"><svg width=24 height=24 viewBox="0 0 22 22" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round aria-hidden=true>${b[2]}</svg><small>${b[0]}</small></span>`).join('')}</div></div>
<div class=ppl>${[['Classes','classes','2'],['Standings','stand','3rd'],['Friends','friends','4'],['Parents','parents','1']].map(p=>`<a class=pp data-go="${p[0]}"><span class=pic>${ic(p[1])}<em>${p[2]}</em></span><span>${p[0]}</span></a>`).join('')}</div>
<a class=tut data-go="Tutoring"><span class=tavs><i>RA</i><i>SK</i><i>MN</i></span><div style="flex:1;min-width:0"><b>Need a hand? Book a tutor</b><span>IGCSE tutors, from 30 minutes</span></div>${CHEV}</a>
<div class=acct>${[['Placement test','Find your starting level'],['Profile and settings',''],['Notifications',''],['Recently deleted','2 papers']].map(r=>`<a class=mrow data-go="${r[0]}"><b>${r[0]}</b><span>${r[1]}</span>${CHEV}</a>`).join('')}</div></div>${TABBAR.replace('<a class=on>','<a>').replace(/<a>(<span class=avm)/,'<a class=on>$1')}`;
put('ME2',ME2);
// polish: every door is a real, focusable link
const linkify=()=>document.querySelectorAll('.phone a:not([href]), .desk a:not([href])').forEach(a=>a.setAttribute('href','#'));
linkify();new MutationObserver(linkify).observe(document.body,{childList:true,subtree:true});
document.addEventListener('click',e=>{if(e.target.closest('a[href="#"]'))e.preventDefault()});
// desktop: side rail (Home, Practice, Subjects, Me + Scan), no tab bar
const DRAIL=on=>`<nav class=rail2><b class=wm2>lemely</b>${[['Home','Home'],['Practice','Practice tab'],['Subjects','Subjects tab'],['Me','Me']].map(([n,g])=>`<a class="${n===on?'on':''}" data-go="${g}">${n}</a>`).join('')}<a class="rscan" data-go="Scan">${CAM.replace('width=26 height=26','width=20 height=20')}Scan a paper</a></nav>`;
function H5D(k){const html=H5(k);const box=document.createElement('div');box.innerHTML=html;
 const pad=box.querySelector('.h4pad');const top=pad.querySelector('.top4'),stage=pad.querySelector('.stage4'),rest=[...pad.children].filter(e=>e!==top&&e!==stage);
 stage.setAttribute('d','');stage.querySelector('.bn').setAttribute('width',200);stage.querySelector('.bn').setAttribute('height',220);
 return `${DRAIL('Home')}<div class=dmain><header class=dtop><h1>Hi, Mariam</h1>${top.outerHTML}</header><div class=dgrid><section class=dstage>${stage.outerHTML}</section><section class=dside>${rest.map(e=>e.outerHTML).join('')}</section></div></div>`}
function MED(){const box=document.createElement('div');box.innerHTML=ME2;const p=box.querySelector('.mepad2');const [hero,strk,stats,bdg,ppl,tut,acct]=[...p.children];
 return `${DRAIL('Me')}<div class=dmain><header class=dtop><h1>Me</h1>${BELL}</header><div class=dgrid me><section class=dcol>${hero.outerHTML}${strk.outerHTML}${stats.outerHTML}${bdg.outerHTML}</section><section class=dcol>${ppl.outerHTML}${tut.outerHTML}${acct.outerHTML}</section></div></div>`}
const _p5=paint5;paint5=k=>{_p5(k);put('D5',H5D(k))};
put('DME',MED());paint5('morning');
// desktop fill: a calm band on Home, subjects + activity on Me
const WEEK=`<div class=bcol><a class="hlink h" data-go="Study plan: this week"><b>This week</b>${SUB}</a><div class=week>${[['Mon',1,'Vectors'],['Tue',1,'Waves'],['Wed',1,'Flashcards'],['Thu',2,'Vectors'],['Fri',0,'Paper 4'],['Sat',0,''],['Sun',0,'']].map((d,i)=>`<a class="wd${d[1]===1?' done':''}${d[1]===2?' now':''}" data-go="Study plan: ${d[0]}"><span>${d[0]}</span><i></i><small>${d[2]}</small></a>`).join('')}</div></div>`;
const RECENT=`<div class=bcol><a class="hlink h" data-go="All papers"><b>Recent papers</b>${SUB}</a>${[['B','--gB','Mathematics · Paper 4','61/80 · 2 days ago'],['C','--gC','Physics · Paper 6','27/40 · last week'],['B','--gB','Add Maths · Paper 2','52/80 · 2 weeks ago']].map(p=>`<a class=rp data-go="Result: ${p[2]}"><b style="color:var(${p[1]})">${p[0]}</b><span class=at><b>${p[2]}</b><span>${p[3]}</span></span>${CHEV}</a>`).join('')}</div>`;
const CLASS=`<div class=bcol><a class="hlink h" data-go="Classes"><b>From your class</b>${SUB}</a><a class=arow data-go="Class thread: your challenge"><span class=tav2>MH</span><span class=at><b>Ms. Hanna replied</b><span>Q7 · she added a mark</span></span>${CHEV}</a><a class=arow data-go="Practice set: Trigonometry"><span class=tav2 style="background:var(--okc);color:var(--ok)">MH</span><span class=at><b>Trigonometry set</b><span>Due Friday · 12 questions</span></span>${CHEV}</a></div>`;
const _h5d=H5D;H5D=k=>_h5d(k).replace(/<\/section><\/div><\/div>$/,`</section><section class=band>${WEEK}${RECENT}${CLASS}</section></div></div>`);
const SUBJ=`<div class=bcol><a class="hlink h" data-go="Subjects tab"><b>Your subjects</b>${SUB}</a>${SUBS.map(s=>`<a class=rp data-go="${s.n} page"><b style="color:var(${GV[s.g]})">${s.g}</b><span class=at><b>${s.n}</b><span>${s.c} · ${s.pts.length} papers · ${s.gap} pts to ${s.next}</span></span>${CHEV}</a>`).join('')}</div>`;
const ACT=`<div class=bcol><b class=acth>Recent activity</b><ul class=act>${[['Earned a badge','Grade up · Mathematics','2 days ago','gold'],['Paper marked','Mathematics P4 · B','2 days ago','p'],['Challenge accepted','Ms. Hanna added a mark to Q7','yesterday','ok'],['Practice done','Vectors · 8 of 10','today','p']].reverse().map(a=>`<li><i class=${a[3]}></i><div><b>${a[0]}</b><span>${a[1]}</span></div><small>${a[2]}</small></li>`).join('')}</ul></div>`;
const _med=MED;MED=()=>_med().replace(/(<section class=dcol>[^]*?)(<\/section><section class=dcol>)/,`$1${SUBJ}$2`).replace(/(<div class="?acct"?>)/,`${ACT}$1`);
put('DME',MED());paint5('morning');
// desktop: "From your class" column owns teacher messages, so drop the duplicate moment row
const _h5d2=H5D;H5D=k=>_h5d2(k).replace(/<a class="?arow"? data-go="Class thread: your challenge"[^]*?<\/a>(?=[^]*<section class=band>)/,'');
paint5('morning');
