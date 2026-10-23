#!/usr/bin/env python3
"""JPX public monthly schedule -> cache. Plans are never released results.
Standard library only; bounded requests and ZIP expansion; no financial figures.
"""
from datetime import datetime, timedelta
from io import BytesIO
import re
import unicodedata
from urllib.parse import urljoin
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
from update_news import host_ok

SOURCE = 'https://www.jpx.co.jp/listing/event-schedules/financial-announcement/'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def worksheet(blob):
    with ZipFile(BytesIO(blob)) as z:
        if len(z.infolist()) > 100 or sum(i.file_size for i in z.infolist()) > 12_000_000:
            raise ValueError('xlsx_expanded_too_large')
        book = ET.fromstring(z.read('xl/workbook.xml'))
        props = book.find('m:workbookPr', NS)
        if props is not None and props.get('date1904') in ('1', 'true'):
            raise ValueError('unsupported_date_epoch')
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS))
                       for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rows = []
        for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:row', NS):
            cells = {}
            for c in row:
                col = re.sub('[0-9]', '', c.get('r', ''))
                v = c.findtext('m:v', '', NS)
                if c.get('t') == 's': v = strings[int(v)]
                if c.get('t') == 'inlineStr': v = ''.join(t.text or '' for t in c.findall('.//m:t', NS))
                cells[col] = unicodedata.normalize('NFKC', v).strip()
            rows.append(cells)
        return rows


def excel_date(value):
    if not re.fullmatch(r'\d{5}', value): return None
    date = (datetime(1899, 12, 30) + timedelta(days=int(value))).date()
    return date.isoformat() if 2000 <= date.year <= 2100 else None


def parse_schedule(blob, members, source_url):
    rows = worksheet(blob)
    header = next((i for i, r in enumerate(rows) if '決算発表予定日' in r.get('A', '') and 'コード' in r.get('B', '') and '会社名' in r.get('C', '')), None)
    if header is None: raise ValueError('schedule_headers_changed')
    if '決算期末' not in rows[header].get('E', '') or '種別' not in rows[header].get('H', ''):
        raise ValueError('schedule_period_headers_changed')
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*現在', ' '.join(v for r in rows[:header] for v in r.values()))
    if not match: raise ValueError('schedule_as_of_missing')
    as_of = datetime(*map(int, match.groups())).date().isoformat()
    items = []
    for row in rows[header+1:]:
        code = row.get('B', '')
        if code not in members: continue
        date = excel_date(row.get('A', ''))
        # Undecided/non-specific dates are not converted into invented dates.
        if not date: continue
        fiscal_end = excel_date(row.get('E', ''))
        period = (fiscal_end + '期末・' if fiscal_end else '') + row.get('H', '')
        items.append(dict(date=date, code=code, company=row.get('C') or members[code], period=period,
                          source_url=source_url, source_as_of=as_of, stage='planned'))
    return items, as_of


def update_schedule(now, downloader, members, previous=None):
    previous = previous or {}
    state = dict(state='failed', checked_at=now.isoformat(timespec='seconds'), source_url=SOURCE,
                 items=previous.get('items', []), sources=previous.get('sources', []), errors=[])
    try:
        # Only the monthly files: next-day workbook has a different schema.
        html = downloader(SOURCE, ['jpx.co.jp']).decode('utf-8')
        links = list(dict.fromkeys(urljoin(SOURCE, u) for u in re.findall(r'href=["\']([^"\']+\.xlsx)["\']', html)
                                   if re.search(r'/kessan\d{2}_\d{4}\.xlsx$', u)))
        links = [u for u in links if host_ok(u, ['jpx.co.jp'])]
        if not links or len(links) > 4: raise ValueError('monthly_links_missing_or_excess')
        found, sources = [], []
        for url in links:
            items, as_of = parse_schedule(downloader(url, ['jpx.co.jp']), members, url)
            if as_of > now.date().isoformat(): raise ValueError('future_snapshot')
            found.extend(items); sources.append(dict(url=url, as_of=as_of))
        unique = {(a['code'], a['period']): a for a in sorted(found, key=lambda a: a['source_as_of'])}
        state.update(state='success', items=sorted(unique.values(), key=lambda a: (a['date'], a['code'])),
                     sources=sources, last_success_at=now.isoformat(timespec='seconds'))
    except (OSError, ValueError, TimeoutError, BadZipFile, KeyError, IndexError, ET.ParseError):
        state['errors'] = ['schedule_fetch_or_parse_failed']
        state['last_success_at'] = previous.get('last_success_at')
    return state
