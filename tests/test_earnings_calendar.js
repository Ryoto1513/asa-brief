const test=require('node:test'), assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../assets/app.js'),'utf8');
const c=vm.createContext({URL,Intl,Date});vm.runInContext(code.slice(0,code.indexOf('let installEvent=')),c);
// Parent integrates the full-date helper from the parallel date change.
vm.runInContext("if(typeof fmtDateLabel==='undefined'){globalThis.fmtDateLabel=d=>d?d.replaceAll('-','/'):'未確認'};localToday=()=> '2026-10-23'",c);
const render=s=>{c.fixture=s;return vm.runInContext('S.earnings={schedule:fixture,items:[]};earningsCalendar()',c)};
test('plans show today/future, never past or detected releases',()=>{
 const plan={date:'2026-10-23',stage:'planned',company:'合成予定',code:'6146',period:'第2四半期',source_url:'https://www.jpx.co.jp/a.xlsx',source_as_of:'2026-10-22'};
 const html=render({state:'success',checked_at:'2026-10-23T09:00:00+09:00',items:[plan,{...plan,company:'未来予定',date:'2026-10-26'},{...plan,company:'範囲外予定',date:'2026-11-06'},{...plan,company:'過去予定',date:'2026-10-22'},{...plan,company:'開示データ',stage:'detected'}]});
 assert.ok(html.includes('合成予定'));assert.ok(html.includes('未来予定'));assert.ok(!html.includes('過去予定'));assert.ok(!html.includes('範囲外予定'));assert.ok(!html.includes('開示データ'));assert.ok(html.includes('2026/10/23'));assert.ok(html.includes('発表済みを意味しません'));
});
test('failure retains visible plans but never claims no scheduled results',()=>{
 const html=render({state:'failed',items:[]});assert.ok(html.includes('最新状況は未確認'));assert.ok(html.includes('予定がないという意味ではありません'));
});
test('schedule separate from released individual detail',()=>{
 c.fixture={state:'success',items:[]};
 const html=vm.runInContext("S.earnings={schedule:fixture,items:[]};S.editorial.articles=[];earningsView()",c);
 assert.ok(html.includes('決算発表の予定'));assert.ok(html.includes('発表済み決算の詳報'));assert.ok(html.includes('新しい決算開示'));assert.equal((html.match(/詳報はまだありません/g)||[]).length,1);
});
