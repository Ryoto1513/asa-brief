"""Focused offline browser fixture: planned calendar is not released earnings.
Imported by browser_editorial; consumes the production assets adjacent to tests.
Does not launch a browser, install dependencies, or contact external sources.
"""
import copy
import json
import re
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-10-23T11:00:00+09:00')


def check_earnings_calendar(browser, fixture):
    data = copy.deepcopy(fixture)
    plan = dict(date='2026-10-23', code='9999', company='合成予定・本日',
                period='2027-03-31期末・第2四半期', stage='planned',
                source_url='https://www.jpx.co.jp/synthetic-fixture.xlsx', source_as_of='2026-10-22')
    rows = [plan, {**plan, 'date': '2026-10-24', 'code': '9998', 'company': '合成予定・翌日'}]
    rows += [{**plan, 'date': '2026-11-05', 'code': str(1000+i), 'company': f'合成多数行{i:02d}'} for i in range(60)]
    rows += [{**plan, 'date': '2026-10-22', 'company': '合成予定・過去除外'},
             {**plan, 'date': '2026-11-06', 'company': '合成予定・範囲外除外'},
             {**plan, 'stage': 'detected', 'company': '合成予定・検知除外'}]
    release = dict(id='synthetic-calendar-release', code='8888', company='合成・発表済み会社',
                   disclosure_key='8888:2026-10-23', title='合成・実際の開示欄', stage='detected',
                   published_at='2026-10-23T09:00:00+09:00', url='https://www.release.tdnet.info/synthetic.pdf')
    data['data/earnings.json'] = dict(schema_version=1, state='success', items=[release],
        schedule=dict(state='success', checked_at='2026-10-23T10:00:00+09:00', items=rows))
    reports = [a for a in data['data/editorial.json']['articles'] if a.get('cat') == '決算' and datetime.fromisoformat(a['published_at']) <= NOW]
    assert reports, 'Caller must provide a released editorial earnings fixture'
    errors, requests = [], []
    context = browser.new_context(viewport={'width': 390, 'height': 844},
                                  is_mobile=True, has_touch=True, service_workers='block')
    context.route('**/*', lambda route: (requests.append(route.request.url), route.abort()))
    page = context.new_page()
    page.clock.install(time=NOW)
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>' + (R / 'assets/style.css').read_text(encoding='utf-8') + '</style>'
            '<main class="shell" id="app"></main><div id="modal"></div>')
        page.add_script_tag(content='window.TEST_DATA=' + json.dumps(data, ensure_ascii=False) + ';'
            'window.TEST_STORE={};'
            "Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.TEST_STORE[k]??null,"
            'setItem:(k,v)=>{window.TEST_STORE[k]=String(v)},removeItem:k=>{delete window.TEST_STORE[k]}}});'
            'window.fetch=async(url)=>{'
            r"let key=String(url).replace(/^\.\//,'').split('?')[0];"
            'return new Response(JSON.stringify(window.TEST_DATA[key]||{}),'
            "{status:window.TEST_DATA[key]?200:404,headers:{'Content-Type':'application/json'}})};")
        page.add_script_tag(content=(R / 'assets/app.js').read_text(encoding='utf-8'))
        page.wait_for_function('!S.loading')
        page.locator('.bottom [data-tab="earnings"]').click()
        table = page.locator('#app .table-scroll').first
        body = page.locator('#app').inner_text()
        assert '2026/10/23〜2026/11/05' in body
        assert '合成予定・本日' in body and '合成予定・翌日' in body
        for absent in ('合成予定・過去除外', '合成予定・範囲外除外', '合成予定・検知除外'):
            assert absent not in body
        assert table.locator('tbody tr').count() == 62
        dates = table.locator('tbody tr td:first-child').all_inner_texts()
        assert all(re.fullmatch(r'\d{4}/\d{2}/\d{2}', date) for date in dates)
        assert dates[0] == '2026/10/23' and dates[-1] == '2026/11/05'
        assert '2026/10/22時点' in table.inner_text()
        assert '2027/03/31' in table.inner_text()
        assert not re.search(r'\d{4}-\d{2}-\d{2}', table.inner_text())
        assert '発表済み決算の詳報' in body and '新しい決算開示' in body
        assert release['company'] not in table.inner_text()
        assert release['company'] in body
        for report in reports:
            assert page.locator('.article-card[data-open="' + report['id'] + '"]').count() == 1
            assert report['title'] not in table.inner_text()
        for width in (320, 375, 390, 430):
            page.set_viewport_size({'width': width, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
            assert table.evaluate('(e)=>e.scrollHeight>e.clientHeight'), width
            table.evaluate('(e)=>e.scrollTop=e.scrollHeight')
            last = table.locator('tbody tr').last
            assert '合成多数行59' in last.inner_text()
            assert last.evaluate('''(e)=>{const row=e.getBoundingClientRect(), box=e.closest('.table-scroll').getBoundingClientRect();return row.bottom<=box.bottom+2&&row.top>=box.top}'''), width
        # Failure/empty never means there are no planned announcements.
        page.evaluate("S.earnings.schedule={state:'failed',items:[]};render()")
        text = page.locator('#app').inner_text()
        assert '最新状況は未確認' in text and '予定がないという意味ではありません' in text
        assert release['company'] in text
        assert not errors, errors
        assert not requests, requests
        return dict(status='PASS', rows=62, range=['2026/10/23', '2026/11/05'],
                    widths=[320, 375, 390, 430], last_row_reachable=True,
                    planned_vs_released_separate=True, javascript_errors=errors, network_requests=requests)
    finally:
        context.close()
