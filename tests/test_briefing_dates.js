// Dependency-free behavioral checks of the production JS, with no network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
const context={console,URL,Intl,Date,Response,navigator:{onLine:true},location:{protocol:'file:',hostname:''},localStorage:{getItem:()=>null,setItem:()=>{}},document:{body:{classList:{toggle(){}},style:{}},documentElement:{style:{}},querySelector:s=>{if(!elements.has(s))elements.set(s,{innerHTML:''});return elements.get(s)},addEventListener(){}},window:{addEventListener(){},scrollTo(){}},setInterval(){},alert(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('assets/app.js','utf8').replace('render();refresh(false);',''),context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 run(`S.editorial={articles:[{id:'old',published_at:'2026-10-20T23:30:00Z',home_until:'2026-10-22T00:00:00+09:00',source_url:'old'},{id:'future',published_at:'2099-01-01T00:00:00Z',home_until:'2099-01-02T00:00:00Z'},{id:'aggregate',published_at:'2026-10-21T01:00:00Z',home_until:'2099-01-02T00:00:00Z'}],briefings:{'2026-10-22':['old']}};S.archiveDates=[];S.latestData={edition_date:'2026-10-23',articles:[{id:'rss23'}]};S.data=S.latestData;`);
 assert.equal(run(`articleDay(S.editorial.articles[0])`),'2026-10-21');
 assert.equal(run(`validDate('2026-02-30')`),false);
 assert.equal(run(`briefingDates().includes('2099-01-01')`),false);
 await run(`selectArchive('2026-10-22')`);
 assert.equal(run(`S.edition`),'2026-10-22');
 assert.equal(run(`JSON.stringify(articleList().map(a=>a.id))`),'["old"]');
 assert.equal(run(`S.data.articles.length`),0); // never attach stale RSS to a different date
 assert.equal(run(`statusType()`),'archive');
 run(`S.tab='topics';S.cat='すべて';S.term='';render()`);
 assert.equal(run(`S.edition`),'2026-10-22');
 assert.equal(run(`findArticle('old').id`),'old');
 await run(`selectArchive('2026-02-30')`);assert.equal(run(`S.edition`),'2026-10-22');
 run(`S.edition='latest';S.editorial.briefings[localToday()]=['old'];`);
 assert.equal(run(`articleList().length`),0); // expired membership cannot revive in latest
 // Newest navigation wins even when older archive response finishes last.
 run(`S.archiveDates=['2026-10-20','2026-10-21'];`);
 let finish;context.fetch=()=>new Promise(resolve=>finish=resolve);
 const pending=run(`selectArchive('2026-10-20')`);
 await run(`selectArchive('2026-10-22')`);
 finish(new Response(JSON.stringify({schema_version:1,edition_date:'2026-10-20',articles:[]})));
 await pending;assert.equal(run(`S.edition`),'2026-10-22');
 context.fetch=async()=>new Response(JSON.stringify({schema_version:1,edition_date:'WRONG',articles:[]}));
 await run(`selectArchive('2026-10-21')`);assert.equal(run(`S.edition`),'2026-10-22');
 console.log('PASS briefing dates: JST, impossible/future dates, explicit membership, expiry, missing RSS, tab persistence, detail lookup, race, mismatched archive');
})().catch(e=>{console.error(e);process.exitCode=1});
