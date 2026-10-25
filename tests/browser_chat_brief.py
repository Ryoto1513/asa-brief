"""Offline Chromium verification of the exact Chat mirror UI. No source fetching.
Uses staged public data, real production assets, and synthetic failure fixtures.
"""
import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright
from browser_earnings_calendar import check_earnings_calendar
R = Path(__file__).resolve().parents[1]

def run(output, public_url=None):
    output.mkdir(parents=True, exist_ok=True)
    data = {p.relative_to(R/'.site').as_posix(): json.loads(p.read_text())
            for p in (R/'.site/data').rglob('*.json')}
    assert data['data/chat-briefs/index.json']['dates']
    day = data['data/chat-briefs/index.json']['dates'][0]
    brief = data[f'data/chat-briefs/{day}.json']
    tomorrow=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
    errors=[]; requests=[]
    if public_url and public_url.rstrip('/') != 'https://ryoto1513.github.io/asa-brief':
        raise ValueError('only the authorized public Pages site may be inspected')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, executable_path=shutil.which("chromium"))
        context=browser.new_context(viewport={'width':390,'height':844},service_workers='block')
        if not public_url: context.add_init_script("""{const Original=Date;const instant=%s;class FixedDate extends Original{constructor(...a){super(...(a.length?a:[instant]));}static now(){return new Original(instant).getTime();}}window.Date=FixedDate;}""" % json.dumps(day+'T23:45:00+09:00'))
        def route(r):
            u=urlparse(r.request.url)
            if u.netloc!='mirror.test':
                r.abort();return
            name=unquote(u.path).removeprefix('/asa-brief/') or 'index.html'
            requests.append(name)
            if name in data:
                r.fulfill(json=data[name]);return
            p=R/name
            if name in ('index.html','assets/app.js','assets/style.css','manifest.webmanifest') and p.is_file():
                r.fulfill(body=p.read_text(),content_type='text/html' if name.endswith('.html') else 'text/css' if name.endswith('.css') else 'application/javascript' if name.endswith('.js') else 'application/json');return
            r.fulfill(status=404,body='not found')
        if not public_url:
            context.route('**/*',route)
        else:
            context.route('**/*',lambda r: r.continue_() if r.request.url.startswith('https://ryoto1513.github.io/asa-brief/') else r.abort())
        page=context.new_page();page.on('pageerror',lambda e: errors.append(str(e)))
        page.goto(public_url or 'https://mirror.test/asa-brief/')
        if public_url:
            page.wait_for_function('(day)=>Array.from(document.querySelectorAll("#briefDate option")).some(o=>o.value===day)',arg=day)
            page.locator('#briefDate').select_option(day)
        page.locator('#chatBrief').wait_for()
        page.wait_for_function('(day)=>S.brief?.edition_date===day',arg=day)
        # Every structured block retains source order, heading level and text.
        def inline(ts):
            return ''.join(t.get('text','') if t['type'] in ('text','link') else inline(t['children']) for t in ts)
        expected=[]
        for b in brief['blocks']:
            if b['type'] in ('heading','paragraph'):expected.append(inline(b['inlines']))
            elif b['type']=='hr':expected.append('')
            elif b['type']=='table':expected.append(''.join(inline(c) for c in b['headers'])+ ''.join(''.join(inline(c) for c in row) for row in b['rows']))
            else:raise AssertionError('extend test for new block type')
        actual=page.locator('#chatBrief').evaluate('(el)=>Array.from(el.querySelectorAll("[data-brief-block]")).map(e=>e.textContent)')
        assert len(actual)==len(expected),(len(actual),len(expected))
        normalize=lambda s: ''.join(s.split())
        assert actual==expected
        heads=[(f"h{b['level']}",inline(b['inlines'])) for b in brief['blocks'] if b['type']=='heading']
        assert page.locator('#chatBrief h1,#chatBrief h2,#chatBrief h3,#chatBrief h4,#chatBrief h5,#chatBrief h6').evaluate_all('(xs)=>xs.map(e=>[e.tagName.toLowerCase(),e.textContent])')==[list(x) for x in heads]
        links=[]
        def gather(ts):
            for t in ts:
                if t['type']=='link':links.append([t['text'],t['url']])
                elif 'children' in t:gather(t['children'])
        for b in brief['blocks']:
            if 'inlines' in b:gather(b['inlines'])
            if b['type']=='table':
                for cell in b['headers']:gather(cell)
                for row in b['rows']:
                    for cell in row:gather(cell)
        assert page.locator('#chatBrief [data-brief-block] a').evaluate_all('(xs)=>xs.map(a=>[a.textContent,a.getAttribute("href")])')==links
        assert page.locator('.bottom button').all_text_contents()==['⌂ブリーフ','▥決算','⚙設定']
        chapters=page.locator('.brief-chapter')
        assert chapters.count()==len([b for b in brief['blocks'] if b['type']=='heading' and b['level']==1])
        assert page.locator('#chatBrief [data-brief-block]').evaluate_all('(xs)=>xs.map(e=>Number(e.dataset.briefBlock))')==list(range(len(expected)))
        assert page.locator('.brief-chapter[open]').count()==2
        # Native summary controls work by keyboard, without changing source content.
        first_summary=chapters.nth(0).locator('summary')
        first_summary.focus();page.keyboard.press('Enter')
        assert chapters.nth(0).get_attribute('open') is None
        page.keyboard.press('Space')
        assert chapters.nth(0).get_attribute('open') is not None
        page.locator('[data-chapters="close"]').click()
        assert page.locator('.brief-chapter[open]').count()==0
        page.screenshot(path=str(output/'chat-brief-chapters-overview.png'))
        page.locator('.brief-toc summary').click()
        toc_links=page.locator('.brief-toc a')
        assert toc_links.count()==chapters.count()
        toc_links.nth(3).click()
        page.wait_for_function('document.querySelectorAll(".brief-chapter")[3].open && document.activeElement===document.querySelectorAll(".brief-chapter>summary")[3]')
        assert chapters.nth(3).get_attribute('open') is not None
        assert page.evaluate('document.activeElement===document.querySelectorAll(".brief-chapter>summary")[3]')
        assert page.evaluate('location.hash').endswith('-chapter-3')
        page.wait_for_function('(()=>{const y=document.querySelectorAll(".brief-chapter")[3].getBoundingClientRect().top;return y>=0 && y<=24})()')
        page.screenshot(path=str(output/'chat-brief-chapter-selected.png'))
        chapters.nth(3).locator('.chapter-return').click()
        assert page.evaluate('location.hash')=='#brief-toc'
        page.go_back()
        page.wait_for_function('location.hash.endsWith("-chapter-3")')
        page.go_forward()
        page.wait_for_function('location.hash==="#brief-toc"')
        page.locator('[data-chapters="open"]').click()
        assert page.locator('.brief-chapter[open]').count()==chapters.count()
        # Same-edition redraw preserves expanded chapters.
        page.locator('[data-tab="settings"]').click();page.locator('[data-tab="home"]').click()
        assert page.locator('.brief-chapter[open]').count()==chapters.count()
        assert page.locator('#chatBrief').evaluate('(el)=>Array.from(el.querySelectorAll("[data-brief-block]")).map(e=>e.textContent)')==expected
        older=[d for d in data['data/chat-briefs/index.json']['dates'] if d!=day]
        if older:
            page.locator('#briefDate').select_option(older[0])
            page.wait_for_function('(d)=>S.brief?.edition_date===d',arg=older[0])
            assert page.evaluate('location.hash')==''
            assert page.locator('.brief-chapter[open]').count()==2
            page.locator('#briefDate').select_option(day)
            page.wait_for_function('(d)=>S.brief?.edition_date===d',arg=day)
            assert page.locator('.brief-chapter[open]').count()==2
        page.locator('[data-chapters="open"]').click()

        for width in (320,375,390,430,1280):
            page.set_viewport_size({'width':width,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            assert page.locator('#chatBrief').evaluate('(e)=>parseFloat(getComputedStyle(e).lineHeight)/parseFloat(getComputedStyle(e).fontSize)>=1.8')
            assert page.locator('#chatBrief').evaluate('(e)=>e.getBoundingClientRect().width<=680')
            assert page.locator('#briefDate').get_attribute('aria-label')=='ブリーフの日付'
            page.screenshot(path=str(output/f'chat-brief-width-{width}.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(output/'chat-brief-mobile.png'))
        page.locator('[data-tab="settings"]').click();page.locator('[data-font="large"]').click();page.locator('[data-theme="dark"]').click();page.locator('[data-tab="home"]').click()
        page.set_viewport_size({'width':320,'height':844})
        assert page.locator('body').evaluate('(e)=>e.classList.contains("dark")&&e.classList.contains("large")')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('[data-chapters="open"]').click()
        table=page.locator('#chatBrief .table-scroll').first
        table.scroll_into_view_if_needed();assert table.evaluate('(e)=>e.scrollWidth>e.clientWidth')
        table.evaluate('(e)=>e.scrollLeft=100');assert table.evaluate('(e)=>e.scrollLeft>0')
        page.screenshot(path=str(output/'chat-brief-dark-large-table.png'))
        page.locator('[data-tab="earnings"]').first.click();assert page.get_by_text('決算発表の予定',exact=True).count()==1
        assert page.get_by_text('新しい決算開示',exact=True).count()==1
        page.screenshot(path=str(output/'chat-brief-earnings.png'))

        for report in data['data/editorial.json']['articles']:
            page.locator('.article-card[data-open="'+report['id']+'"]').click()
            modal=page.locator('#articlePage')
            assert modal.locator('h1').inner_text()==report['title']
            assert modal.locator('.lede').inner_text()==report['lead']
            tables=[b for b in report['blocks'] if b['type']=='table']
            assert modal.locator('table').count()==len(tables)
            for n,b in enumerate(tables):
                rows=modal.locator('table').nth(n).locator('tbody tr')
                assert rows.count()==len(b['rows'])
                for i,row in enumerate(b['rows']):
                    assert rows.nth(i).locator('th,td').all_text_contents()==[str(v) for v in row]
            for block in report['blocks']:
                for paragraph in block.get('paragraphs',[]):
                    assert paragraph in modal.text_content()
            page.screenshot(path=str(output/'chat-brief-earnings-detail.png'))
            page.keyboard.press('Escape')
            assert page.locator('#articlePage').count()==0
            assert page.locator('.bottom [data-tab="earnings"]').get_attribute('class').endswith('active')

        # Main must not fetch or expose historical RSS/saved stories.
        assert not any(n in ('data/latest.json','data/archive/index.json','data/status.json') for n in requests)
        page.locator('[data-tab="home"]').click()
        if not public_url:
            # Actual brief response provenance controls the offline indicator.
            page.evaluate(r"""async()=>{const original=readJSON;window.testOriginalRead=original;readJSON=async p=>{const r=await original(p);if(/chat-briefs\/\d/.test(p))r.cached=true;return r;};await refresh();}""")
            assert page.get_by_text('オフライン・保存済みの本文です。最新の改訂は未確認です。',exact=False).count()==1
            # A failure preserves displayed document and date, explicitly flagged.
            page.evaluate("async()=>{readJSON=async()=>{throw Error('synthetic failure')};await refresh();}")
            assert page.locator('#chatBrief').count()==1
            assert page.get_by_text('再取得に失敗しました。表示中の本文を保持しています。',exact=False).count()==1
            # Real body tampering, not just a different declared hash, is rejected.
            page.evaluate("async day=>{readJSON=async p=>{const r=await testOriginalRead(p);if(p.endsWith(day+'.json'))r.data={...r.data,body_markdown:r.data.body_markdown+'tampered'};return r;};await refresh();}",day)
            assert page.evaluate('S.briefError')=='fetch'
            assert page.evaluate('S.brief.body_markdown')==brief['body_markdown']
            # At JST rollover, even failed index fetch cannot label yesterday as today.
            page.evaluate("async tomorrow=>{window.realLocalToday=localToday;localToday=()=> tomorrow;readJSON=async()=>{throw Error('midnight failure')};await refresh();}",tomorrow)
            assert page.locator('#chatBrief').count()==0
            page.evaluate('localToday=realLocalToday')
            # Missing today does not relabel prior content as today's edition.
            page.evaluate("async()=>{readJSON=testOriginalRead;S.briefIndex={dates:[],editions:[]};await loadBriefDay('latest',++S.editionRequest);render();}")
            assert page.locator('#chatBrief').count()==0
            assert page.get_by_text('本日分は未反映です',exact=True).count()==1
            # Delayed older selection cannot overwrite a newer selection.
            result=page.evaluate("""async()=>{const today=localToday();const b=%s;const old='2026-10-23';S.briefIndex={dates:[today,old],editions:[{edition_date:today,body_sha256:b.body_sha256,source_updated_at:b.source_updated_at},{edition_date:old,body_sha256:b.body_sha256,source_updated_at:b.source_updated_at}]};readJSON=async p=>{if(p.includes(old)){await new Promise(r=>setTimeout(r,60));return {data:{...b,edition_date:old},cached:false};}return {data:b,cached:false};};await Promise.all([selectArchive(old),selectArchive(today)]);return S.edition;}""" % json.dumps(brief))
            assert result==day
            # Escaping and fail-closed unknown tokens/URLs.
            assert page.evaluate("briefInlines([{type:'text',text:'<img src=x onerror=alert(1)>'}])")== '&lt;img src=x onerror=alert(1)&gt;'
            for token in ({'type':'html','text':'<script>'},{'type':'link','text':'x','url':'javascript:alert(1)'},{'type':'link','text':'x','url':'https://chatgpt.com/c/private'}):
                assert page.evaluate('(t)=>{try{briefInlines([t]);return false}catch(_){return true}}',token)
        if not public_url:
            # Renderer grouping preserves synthetic preamble, list and duplicate titles.
            synthetic=[{'type':'paragraph','inlines':[{'type':'text','text':'intro'}]},{'type':'heading','level':1,'inlines':[{'type':'text','text':'same'}]},{'type':'list','ordered':False,'items':[[{'type':'text','text':'list item'}]]},{'type':'heading','level':1,'inlines':[{'type':'text','text':'same'}]}]
            assert page.evaluate('(bs)=>briefChapters(bs).flatMap(c=>c.blocks)',synthetic)==synthetic
        assert not errors,errors
        calendar_report=check_earnings_calendar(browser,data) if not public_url else None
        browser.close()
    report={'calendar_regression':calendar_report,'passed':True,'mode':'public_read_only' if public_url else 'offline_fixture','edition':day,'blocks':len(expected),'source_links':len(links),'widths':[320,375,390,430,1280],'checks':['chapter cards and unique block indices','native keyboard open/close','expand all and collapse all','TOC focus and hash navigation','Back/Forward','date changes reset chapter state','block text and order','heading hierarchy','source labels and destinations','table scroll','large dark','earnings','no RSS requests','offline provenance','failure retains content','missing today','rapid date race','unsafe tokens rejected'],'limitations':['Chromium fixture only; not real Safari or real Service Worker installation']}
    if public_url:
        report['checks']=['chapter keyboard and TOC','all chapters reachable','date reset and Back/Forward','public body text and order','public heading hierarchy','public source labels and destinations','table scroll','large dark','earnings']
        report['limitations']=['Chromium; Service Worker blocked for fresh public-file verification; not real Safari']
    (output/'chat-brief-browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-dir',type=Path,default=R/'browser-artifacts/chat-brief');parser.add_argument('--public-url');args=parser.parse_args();run(args.output_dir,args.public_url)
