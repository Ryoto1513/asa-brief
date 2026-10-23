"""Injected/offline date-filter UI contract, called by browser_editorial CI."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1]

def check_briefing_dates(browser, fixture):
    data=copy.deepcopy(fixture)
    story=copy.deepcopy(data['data/editorial.json']['articles'][0])
    story.update(id='expired-date-story',title='合成テスト：日付別の過去詳報',published_at='2026-10-20T23:30:00Z',home_until='2026-10-22T00:00:00+09:00',date='10/21')
    data['data/editorial.json']['articles'].insert(0,story)
    data['data/editorial.json']['briefings']={'2026-10-22':[story['id']]}
    data['data/archive/index.json']={'dates':['2026-10-20']}
    data['data/archive/2026-10-20.json']={'schema_version':1,'status':'live','edition_date':'2026-10-20','articles':[]}
    context=browser.new_context(viewport={'width':390,'height':844},service_workers='block')
    requests=[];errors=[]
    context.route('**/*',lambda route:(requests.append(route.request.url),route.abort()))
    page=context.new_page();page.clock.install(time=datetime(2026,10,23,3,tzinfo=timezone.utc))
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1"><style>'+(R/'assets/style.css').read_text()+'</style><main class="shell" id="app"></main><div id="modal"></div>')
    page.add_script_tag(content='window.TEST_DATA='+json.dumps(data,ensure_ascii=False)+''';window.TEST_STORE={};Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.TEST_STORE[k]??null,setItem:(k,v)=>{window.TEST_STORE[k]=String(v)}}});window.fetch=async(url)=>{let key=String(url).replace(/^\\.\\//,'').split('?')[0];return new Response(JSON.stringify(window.TEST_DATA[key]||{}),{status:window.TEST_DATA[key]?200:404,headers:{'Content-Type':'application/json'}})};''')
    page.add_script_tag(content=(R/'assets/app.js').read_text());page.wait_for_function('!S.loading')
    assert page.locator('#briefDate').is_visible()
    assert page.locator('.bottom .tab').count()==5
    assert page.locator('[data-open="expired-date-story"]').count()==0
    page.locator('#briefDate').select_option('2026-10-22')
    assert page.locator('.article-card').count()==1
    assert page.locator('#briefDate').input_value()=='2026-10-22'
    assert '2026-10-22' in page.locator('.date-note').inner_text()
    assert page.locator('.sectionbar h2').inner_text()=='この日のブリーフ'
    assert page.evaluate('S.data.articles.length')==0
    page.locator('[data-bookmark="expired-date-story"]').click()
    page.locator('[data-open="expired-date-story"]').click()
    assert page.locator('#articlePage h1').inner_text()==story['title']
    page.locator('[data-close]').first.click()
    page.locator('.bottom [data-tab="topics"]').click()
    assert page.locator('#briefDate').input_value()=='2026-10-22'
    page.locator('#searchInput').fill('該当なし')
    assert page.locator('#topicResults .article-card').count()==0
    page.locator('#searchInput').fill('')
    page.locator('.bottom [data-tab="saved"]').click()
    assert page.locator('[data-open="expired-date-story"]').count()==1
    page.locator('.bottom [data-tab="home"]').click()
    page.locator('#briefDate').select_option('2026-10-20')
    page.wait_for_function("S.edition==='2026-10-20'")
    assert page.locator('.article-card').count()==0
    page.locator('#briefDate').select_option('latest')
    page.wait_for_function("S.edition==='latest'&&!S.loading")
    assert page.locator('[data-open="expired-date-story"]').count()==0
    # More than twelve entries: latest stays concise, a selected day shows all.
    page.evaluate('''() => {
        const sample=window.TEST_DATA['data/latest.json'].articles[0];
        window.TEST_DATA['data/editorial.json']={schema_version:1,articles:[]};
        window.TEST_DATA['data/latest.json'].articles=Array.from({length:15},(_,i)=>({...sample,
            id:'full-day-'+i,title:'合成テスト：日付別の全件 '+i,source_url:'https://example.com/full-day-'+i}));
    }''')
    page.locator('[data-refresh]').first.click()
    page.wait_for_function("S.edition==='latest'&&!S.loading")
    assert page.locator('.article-card').count()==12
    page.locator('#briefDate').select_option('2026-10-23')
    page.wait_for_function("S.edition==='2026-10-23'")
    assert page.locator('.article-card').count()==15
    page.locator('[data-open="full-day-14"]').click()
    assert page.locator('#articlePage h1').inner_text()=='合成テスト：日付別の全件 14'
    page.locator('[data-close]').first.click()
    for width in (320,375,390,430):
        page.set_viewport_size({'width':width,'height':844})
        assert page.locator('#app').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
    assert not errors,errors
    assert not requests,requests
    context.close()
    return {'status':'PASS','tests':['visible date filter','expired editorial without RSS','JST membership','detail/bookmark','tabs/search','empty archive','return latest','selected day shows all 15, latest capped at 12','mobile widths'],'network_requests':requests,'javascript_errors':errors}
