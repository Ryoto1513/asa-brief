// Dependency-free behavioral checks of the production JS, with no network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map();
class FixedDate extends Date {constructor(...args){super(...(args.length?args:['2026-10-23T03:00:00Z']))}static now(){return new Date('2026-10-23T03:00:00Z').getTime()}}
const context={console,URL,Intl,Date:FixedDate,Response,navigator:{onLine:true},location:{protocol:'file:',hostname:''},localStorage:{getItem:()=>null,setItem:()=>{}},document:{body:{classList:{toggle(){}},style:{}},documentElement:{style:{}},querySelector:s=>{if(!elements.has(s))elements.set(s,{innerHTML:''});return elements.get(s)},addEventListener(){}},window:{addEventListener(){},scrollTo(){}},setInterval(){},alert(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync('assets/app.js','utf8').replace('render();refresh(false);',''),context);
const run=s=>vm.runInContext(s,context);
(async()=>{
 run(`S.editorial={articles:[{id:'old',published_at:'2026-10-20T23:30:00Z',home_until:'2026-10-22T00:00:00+09:00',source_url:'old'},{id:'future',published_at:'2099-01-01T00:00:00Z',home_until:'2099-01-02T00:00:00Z'},{id:'aggregate',published_at:'2026-10-21T01:00:00Z',home_until:'2099-01-02T00:00:00Z'}],briefings:{'2026-10-22':['old']}};S.archiveDates=[];S.latestData={edition_date:'2026-10-23',articles:[{id:'rss23'}]};S.data=S.latestData;`);
 assert.equal(run(`articleDay(S.editorial.articles[0])`),'2026-10-21');
 assert.equal(run(`validDate('2026-02-30')`),false);
 assert.equal(run(`briefingDates().includes('2099-01-01')`),false);
 await run(`selectArchive('2026-10-21')`);
 assert.equal(run(`S.edition`),'2026-10-21');
 assert.equal(run(`JSON.stringify(articleList().map(a=>a.id))`),'["old","aggregate"]');
 assert.equal(run(`S.data.articles.length`),0); // never attach stale RSS to a different date
 assert.equal(run(`statusType()`),'archive');
 run(`S.tab='topics';S.cat='すべて';S.term='';render()`);
 assert.equal(run(`S.edition`),'2026-10-21');
 assert.equal(run(`findArticle('old').id`),'old');
 await run(`selectArchive('2026-02-30')`);assert.equal(run(`S.edition`),'2026-10-21');
 run(`S.edition='latest';S.editorial.briefings[localToday()]=['old'];`);
 assert.equal(run(`articleList().length`),0); // expired membership cannot revive in latest
 // Newest navigation wins even when older archive response finishes last.
 run(`S.archiveDates=['2026-10-20','2026-10-22'];`);
 let finish;context.fetch=()=>new Promise(resolve=>finish=resolve);
 const pending=run(`selectArchive('2026-10-20')`);
 await run(`selectArchive('2026-10-21')`);
 finish(new Response(JSON.stringify({schema_version:1,edition_date:'2026-10-20',articles:[]})));
 await pending;assert.equal(run(`S.edition`),'2026-10-21');
 context.fetch=async()=>new Response(JSON.stringify({schema_version:1,edition_date:'WRONG',articles:[]}));
 await run(`selectArchive('2026-10-22')`);assert.equal(run(`S.edition`),'2026-10-21');
 // The selected day's home must not silently truncate articles after twelve.
 run(`S.editorial={articles:[]};S.data={edition_date:'2026-10-23',status:'live',articles:Array.from({length:15},(_,i)=>({id:'day-item-'+i,title:'Day item '+i,published_at:'2026-10-23T00:00:00Z',source_url:'https://example.com/'+i}))};S.latestData=S.data;S.edition='latest';S.tab='home';`);
 assert.equal(run(`(home().match(/class="card article-card"/g)||[]).length`),15);
 await run(`selectArchive('2026-10-23')`);
 assert.equal(run(`(home().match(/class="card article-card"/g)||[]).length`),15);
 assert.equal(run(`home().includes('data-open="day-item-14"')`),true);
 // Selected day ignores curation membership, filters RSS independently, and uses JST.
 run(`S.editorial={articles:[
 {id:'old21',published_at:'2026-10-21T00:00:00Z',home_until:'2099-01-01',source_url:'21'},
 {id:'old22',published_at:'2026-10-22T14:59:59Z',home_until:'2099-01-01',source_url:'22'},
 {id:'boundary23',published_at:'2026-10-22T15:00:00Z',home_until:'2099-01-01',source_url:'23'}
 ],briefings:{[localToday()]:['old21','old22']}};
 S.data.articles=[{id:'rss22',published_at:'2026-10-22T14:59:59Z',source_url:'r22'},
 {id:'rss23',published_at:'2026-10-22T15:00:00Z',source_url:'r23'},
 {id:'rss21',published_at:'2026-10-21T01:00:00Z',source_url:'r21'}];S.edition='2026-10-23';`);
 assert.equal(run(`JSON.stringify(articleList().map(a=>a.id))`),'["boundary23","rss23"]');
 assert.equal(run(`fmtDateLabel('2026-10-23')`),'2026/10/23');
 assert.equal(run(`fmtDateLabel('2026-10-22T15:00:00Z')`),'2026/10/23');
 assert.equal(run(`fmtTime('2026-10-22T15:00:00Z')`),'2026/10/23 00:00 JST');
 assert.equal(run(`dateFilter().includes('value="2026-10-23" selected>2026/10/23</option>')`),true);
 assert.equal(run(`dateNote().includes('2026/10/23')`),true);
 assert.equal(run(`artCard(S.editorial.articles[2]).includes('2026/10/23')`),true);
 run(`S.edition='latest'`);
 assert.equal(run(`JSON.stringify(articleList().map(a=>a.id))`),'["boundary23","rss23"]');
 assert.equal(run(`JSON.stringify(topicArticles().map(a=>a.id))`),'["old21","old22","boundary23","rss22","rss23","rss21"]');
 // Topics uses retained archives, deduplicates ID and URL, retries failures, caches successes.
 run(`S.tab='topics';S.edition='2026-10-21';S.archiveDates=['2026-10-20','2026-10-19'];S.topicArchives={};`);
 let calls=[];
 context.fetch=async url=>{calls.push(url);const d=url.match(/(2026-10-\d+)/)[1];return new Response(JSON.stringify({schema_version:1,edition_date:d,articles:[
 {id:'archived-'+d,published_at:d+'T00:00:00Z',source_url:'archive-shared',cat:'日本経済',title:'過去RSS'},
 {id:'rss22',published_at:d+'T00:00:00Z',source_url:'duplicate-id'}]}))};
 await run(`loadTopicArchives()`);
 assert.equal(calls.length,2);
 assert.equal(run(`topicArticles().filter(a=>a.source_url==='archive-shared').length`),1);
 assert.equal(run(`topicArticles().filter(a=>a.id==='rss22').length`),1);
 assert.equal(run(`S.edition`),'2026-10-21');
 assert.equal(run(`topics().includes('id="briefDate"')`),false);
 run(`S.cat='日本経済';S.term='過去RSS'`);
 assert.equal(run(`filteredArticles().length`),1);
 assert.equal(run(`findArticle('archived-2026-10-20').title`),'過去RSS');
 await run(`loadTopicArchives()`);assert.equal(calls.length,2);
 run(`S.archiveDates=['2026-10-18']`);context.fetch=async()=>{throw Error('offline')};
 await run(`loadTopicArchives()`);assert.equal(run(`S.topicArchiveFailed`),true);
 assert.equal(run(`topicLibraryNote().includes('一部の過去の見出しを取得できません')`),true);
 context.fetch=()=>new Promise(resolve=>finish=resolve);
 const archivePending=run(`loadTopicArchives()`);
 run(`S.tab='home';S.edition='2026-10-23';S.selected='boundary23'`);
 finish(new Response(JSON.stringify({schema_version:1,edition_date:'2026-10-18',articles:[]})));
 await archivePending;
 assert.equal(run(`S.tab`),'home');assert.equal(run(`S.edition`),'2026-10-23');assert.equal(run(`S.selected`),'boundary23');
 run(`S.archiveDates=Array.from({length:20},(_,i)=>'2026-09-'+String(i+1).padStart(2,'0'));S.topicArchives={}`);
 calls=[];context.fetch=async url=>{calls.push(url);return new Response('{}')};
 await run(`loadTopicArchives()`);assert.equal(calls.length,14);
 console.log('PASS strict publication-day filtering, JST boundary, 15 selected-day cards, slash labels, Today current-day filtering and Topics all dates, navigation and archive safeguards');
})().catch(e=>{console.error(e);process.exitCode=1});
