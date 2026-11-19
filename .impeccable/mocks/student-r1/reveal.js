(()=>{
/* Official Binny geometry from web/src/portals/marketing/Binny.tsx + binny.svg (paper sheet always clipped underneath). Sad is the one added expression. */
const BIN='#042f4f',INK='#130e10';
function binny(mood){const sad=mood==='sad',happy=mood==='happy',wink=mood==='wink',open=mood==='open';
const el=-10,er=14,eL=sad?-30:el,eR=sad?30:er;
const eyeL=happy?`<path d="M68 143 Q78 130 88 143" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/>`:`<ellipse cx="78" cy="140" rx="11" ry="12" fill="#fff"/><circle cx="${sad?77:80}" cy="${sad?146:141}" r="6.5" fill="${INK}"/>`;
const eyeR=happy||wink?`<path d="M112 143 Q122 130 132 143" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/>`:`<ellipse cx="122" cy="140" rx="11" ry="12" fill="#fff"/><circle cx="${sad?123:124}" cy="${sad?146:141}" r="6.5" fill="${INK}"/>`;
const mouth=open?`<path d="M86 160 H114 Q113 180 100 180 Q87 180 86 160Z" fill="${INK}" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>`:sad?`<path d="M90 171 Q100 160 110 171" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round"/>`:`<path d="M90 163 Q100 172 110 163" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round"/>`;
return `<svg viewBox="0 0 200 220" aria-hidden="true" class="${happy?'wig':''}"><rect fill="#fff" x="54" y="168" width="92" height="48" rx="4" stroke="oklch(.88 .008 240)" stroke-width="2" transform="rotate(-3 100 192)"/><g class="ear ear-l" style="transform:rotate(${eL}deg);transform-origin:75px 100px"><path d="M66 102 L62 40 Q62 16 75 16 Q88 16 88 40 L84 102" fill="none" stroke="var(--b16)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></g><g class="ear ear-r" style="transform:rotate(${eR}deg);transform-origin:125px 100px"><path d="M116 102 L112 40 Q112 16 125 16 Q138 16 138 40 L134 102" fill="none" stroke="var(--b16)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/></g><path d="M40 104 H160 L152 186 Q151 196 141 196 H59 Q49 196 48 186 Z" fill="${BIN}"/><rect x="34" y="94" width="132" height="18" rx="8" fill="var(--b17)"/><ellipse cx="62" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--b18)"/><ellipse cx="138" cy="160" rx="9" ry="5.5" opacity=".55" fill="var(--b18)"/><g class="eyes-g">${eyeL}${eyeR}</g>${mouth}</svg>`}
const G={'A*':{s:74,c:'oklch(.46 .12 155)',t:'a',m:'happy',l:'An A*. Your examiner would be proud. Probably.',d:'+9 vs last paper'},
A:{s:67,c:'oklch(.52 .12 132)',t:'a',m:'happy',l:'An A! 3 marks from an A*.',d:'+6 vs last paper'},
B:{s:61,c:'oklch(.58 .12 110)',t:'b',m:'wink',l:'Solid B. 4 marks to an A.',d:'+4 vs last paper'},
C:{s:50,c:'oklch(.63 .12 88)',t:'c',m:'open',l:'A C, and a clear route up.',d:'+2 vs last paper'},
D:{s:41,c:'oklch(.59 .125 62)',t:'d',m:'sad',l:'Tough one. Here is exactly where the marks are.',d:'−3 vs last paper'},
U:{s:22,c:'oklch(.5 .14 15)',t:'d',m:'sad',l:'Not this time. Every lost mark shows you what to practise.',d:'−9 vs last paper'}};
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)],sleep=ms=>new Promise(r=>setTimeout(r,ms));
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
let grade='B',token=0,tension=0;const phone=$('.phone'),ov=$('#ov'),fly=$('#fly'),slot=$('#slotb'),hold=$('#hold');
function fill(){const g=G[grade];$('#gc').style.background=g.c;$('#gc').textContent=grade;$('#sc').firstChild.nodeValue=g.s;
$('#hgrade').textContent=grade;$('#hgrade').style.background=g.c;$('#hscore').firstChild.nodeValue=g.s;$('#hdelta').textContent=g.d;$('#hline').textContent=g.l;$('#hl').textContent=g.l;
const lost=80-g.s;setLost(lost);$('#nxp').textContent=lost>6?`Those two answers hold 6 of your ${lost} lost marks.`:'Win those two back for full marks.'}
function setBinny(el,mood,idle){el.innerHTML=binny(mood);el.firstChild.classList.toggle('bb-idle',!!idle)}
/* suspense: tension follows the hold progress */
let lastScr=0;
function tick(t){if(ov.classList.contains('go')||ov.classList.contains('gone'))return;
const p=parseFloat(hold.style.getPropertyValue('--hp'))||0;tension=p;ov.style.setProperty('--tn',p);
hold.style.setProperty('--hb',(1.4-p*0.95).toFixed(2)+'s');
ov.classList.toggle('shake',!reduce&&p>.6);
const hint=p>.85?'Here it comes':p>.6?'Almost…':p>.02?'Keep holding':'Hold to reveal';if($('#hint').textContent!==hint)$('#hint').textContent=hint;
if(!reduce&&p>.02&&t-lastScr>150-p*110){lastScr=t;$('#sa').textContent=Math.floor(Math.random()*10);$('#sb').textContent=Math.floor(Math.random()*10)}
if(p<=.02){$('#sa').textContent='?';$('#sb').textContent='?'}
requestAnimationFrame(tick)}
function reset(){token++;ov.className='ov dark';ov.style.setProperty('--tn',0);document.body.classList.remove('revealed');document.body.classList.add('ovl');hold.style.setProperty('--hp',0);fly.classList.remove('on');fly.style.display='block';fly.getAnimations().forEach(a=>a.cancel());fly.style.transform='translate(135px,900px)';slot.innerHTML='';$('#sc').firstChild.nodeValue='0';$('#hint').textContent='Hold to reveal';fill();$('.scroller').scrollTop=0;requestAnimationFrame(tick)}
function hop(from,to,dur,h){const mx=(from.x+to.x)/2,my=Math.min(from.y,to.y)-h,r=(to.x-from.x)/18;
return fly.animate([{transform:`translate(${from.x}px,${from.y}px) scale(1.14,.84)`,offset:0},{transform:`translate(${from.x}px,${from.y}px) scale(.92,1.12)`,offset:.12},{transform:`translate(${mx}px,${my}px) scale(.94,1.1) rotate(${r}deg)`,offset:.5},{transform:`translate(${to.x}px,${to.y}px) scale(1.16,.82)`,offset:.9},{transform:`translate(${to.x}px,${to.y}px) scale(1)`,offset:1}],{duration:dur,easing:'cubic-bezier(.3,.6,.3,1)',fill:'forwards'}).finished}
function count(to,dur,my){return new Promise(res=>{const t0=performance.now();const f=()=>{if(my!==token)return res();const p=Math.min((performance.now()-t0)/dur,1),e=1-Math.pow(1-p,3);$('#sc').firstChild.nodeValue=Math.round(to*e);p<1?requestAnimationFrame(f):res()};f()})}
/* free zone: everything below the button. Binny never enters the result stack. */
function zone(){const pr=phone.getBoundingClientRect(),br=$('#go2').getBoundingClientRect();const cb=br.bottom-pr.top;ov.style.setProperty('--cb',cb+'px');return{top:cb+44,bottom:844-132-8}}
function rest(){const z=zone();return{x:135,y:Math.min(Math.max(z.top+30,z.bottom-20),z.bottom)}}
const clampY=(y,z)=>Math.min(Math.max(y,z.top),z.bottom);
async function reveal(){const my=token,g=G[grade];ov.classList.remove('dark','shake');ov.classList.add('go','tier-'+g.t,'flash');document.body.classList.add('revealed');
setBinny(fly,g.m,false);fly.style.transform='translate(135px,900px)';fly.classList.add('on');count(g.s,reduce?1:1100,my);
const R=rest(),Z=zone();
if(reduce){fly.style.transform=`translate(${R.x}px,${R.y}px)`;ov.classList.add('ready');return}
await sleep(900);if(my!==token)return;
let cur={x:135,y:900};
const go=(to,dur,h)=>{to={x:to.x,y:clampY(to.y,Z)};const peakRoom=Math.min(cur.y,to.y)-Z.top;const hh=Math.max(0,Math.min(h,peakRoom));const p=hop(cur,to,dur,hh);cur=to;return p};
if(g.t==='a'){for(const [x,y] of [[14,R.y],[256,R.y-30],[20,R.y],[250,R.y-60],[135,R.y]]){if(my!==token)return;await go({x,y},640,170)}}
else if(g.t==='b'){for(const to of [{x:70,y:R.y},{x:200,y:R.y}]){if(my!==token)return;await go(to,720,100);await sleep(120)}}
else{await go({x:135,y:R.y},1000,70)}
if(my!==token)return;await go(R,600,90);
fly.firstChild.classList.add('bb-idle');fly.dataset.x=cur.x;fly.dataset.y=cur.y;ov.classList.add('ready')}
/* dock: Binny fades out where it stands (empty field), then the card's Binny pops in. No flight across content. */
async function dock(){const my=token;
fly.firstChild.classList.remove('bb-idle');
if(!reduce){await fly.animate([{opacity:1},{opacity:0}],{duration:320,easing:'ease-out',fill:'forwards'}).finished}
if(my!==token)return;
ov.classList.add('out');document.body.classList.remove('ovl');
await sleep(reduce?0:420);if(my!==token)return;
fly.style.display='none';setBinny(slot,G[grade].m,true);slot.classList.remove('pop');void slot.offsetWidth;slot.classList.add('pop');ov.classList.add('gone')}
const R0=()=>rest().y;
const mo=new MutationObserver(()=>{if(document.body.classList.contains('revealed')&&!ov.classList.contains('go'))reveal()});mo.observe(document.body,{attributes:true,attributeFilter:['class']});
document.addEventListener('click',e=>{if(e.target.closest('#go2'))dock();const gb=e.target.closest('[data-grade]');if(gb){grade=gb.dataset.grade;$$('[data-grade]').forEach(b=>b.classList.toggle('on',b===gb));reset()}if(e.target.closest('[data-replay]'))setTimeout(reset,0)});
reset();
})();
