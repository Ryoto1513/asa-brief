#!/usr/bin/env python3
"""Bounded public-disclosure monitor. Detection is NOT a completed earnings analysis.
Reads current Nikkei components and TDnet's public daily HTML. No credentials,
no article/PDF copying, and no inference of financial numbers from headlines.
"""
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
from update_news import download,atomic_json,host_ok
R=Path(__file__).resolve().parents[1]
JST=timezone(timedelta(hours=9))
COMPONENTS='https://indexes.nikkei.co.jp/nkave/index/component'
TDNET='https://www.release.tdnet.info/inbs/'

class Rows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None;self.links=[];self.cells=[];self.all_links=[];self.depth=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='tr':self.row=[];self.links=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
        if tag=='a' and a.get('href'):
            self.all_links.append(a['href'])
            if self.row is not None:self.links.append(a['href'])
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r'\s+',' ',' '.join(self.cell)).strip());self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append((self.row,self.links));self.row=None;self.cell=None

def parse_components(blob):
    p=Rows();p.feed(blob.decode('utf-8',errors='replace'));members={}
    for cells,_ in p.rows:
        if len(cells)>=2 and re.fullmatch(r'[0-9][0-9A-Z]{3}',cells[0]):members[cells[0]]=cells[-1]
    if len(members)!=225:raise ValueError('component_count_not_225')
    return members

def parse_disclosures(blob,date,members):
    p=Rows();p.feed(blob.decode('utf-8',errors='replace'));items=[]
    for cells,links in p.rows:
        if len(cells)<4:continue
        tm=next((v for v in cells if re.fullmatch(r'\d{2}:\d{2}',v)),None)
        codeidx=next((i for i,v in enumerate(cells) if re.fullmatch(r'[0-9][0-9A-Z]{3}0?',v)),None)
        if not tm or codeidx is None:continue
        code=cells[codeidx][:4]
        if code not in members:continue
        title=next((v for v in cells if re.search(r'決算短信|業績予想.*修正|業績予想のお知らせ|配当予想.*修正',v)),None)
        if not title:continue
        pdfs=[urljoin(TDNET,u) for u in links if re.search(r'\.pdf(?:[?#]|$)',u,re.I)]
        pdfs=[u for u in pdfs if host_ok(u,['release.tdnet.info'])]
        if not pdfs:continue
        company=cells[codeidx+1] if codeidx+1<len(cells) else members[code]
        key=f'{code}:{date}'
        items.append({'id':hashlib.sha256(pdfs[0].encode()).hexdigest()[:20],'disclosure_key':key,'code':code,'company':company,'title':title,'published_at':f'{date}T{tm}+09:00','url':pdfs[0],'stage':'detected'})
    return items,p.all_links

def update_watch(now=None,downloader=download,data_dir=None):
    now=(now or datetime.now(JST)).astimezone(JST);d=Path(data_dir or R/'data');previous={}
    try:previous=json.loads((d/'earnings.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    previous_items=[x for x in previous.get('items',[]) if x.get('published_at','')>=(now-timedelta(days=30)).date().isoformat()]
    state={'schema_version':1,'checked_at':now.isoformat(timespec='seconds'),'state':'uninitialized','items':previous_items,'universe_count':0,'pages_requested':0,'pages_ok':0,'errors':[]}
    try:members=parse_components(downloader(COMPONENTS,['indexes.nikkei.co.jp']));state['universe_count']=len(members)
    except (OSError,ValueError,TimeoutError) as exc:
        state.update(state='failed',message='構成銘柄の取得・照合に失敗。過去に検知した開示のみ保持しています。')
        state['errors'].append('component_fetch_or_parse_failed');atomic_json(d/'earnings.json',state);return state
    found=[]
    for ago in range(3):
        date=(now-timedelta(days=ago)).date();stamp=date.strftime('%Y%m%d');queue=[f'{TDNET}I_list_001_{stamp}.html'];visited=set()
        while queue and len(visited)<3:
            url=queue.pop(0)
            if url in visited:continue
            visited.add(url);state['pages_requested']+=1
            try:
                blob=downloader(url,['release.tdnet.info'])
                if not re.search(br'<(?:table|tr)[\s>]',blob,re.I):raise ValueError('unexpected_html')
                items,links=parse_disclosures(blob,date.isoformat(),members);found.extend(items);state['pages_ok']+=1
                for u in links:
                    full=urljoin(url,u)
                    if re.search(r'I_list_\d{3}_'+stamp+r'\.html$',full) and host_ok(full,['release.tdnet.info']) and full not in visited and full not in queue:queue.append(full)
            except (OSError,ValueError,TimeoutError):state['errors'].append(date.isoformat()+':listing_unavailable')
    unique={a['id']:a for a in previous_items}
    unique.update({a['id']:a for a in found if a['published_at']<=now.isoformat(timespec='seconds')})
    state['items']=sorted(unique.values(),key=lambda a:a['published_at'],reverse=True)[:150]
    state['state']='success' if state['pages_ok']==state['pages_requested'] else 'partial' if state['pages_ok'] else 'failed'
    state['message']={'success':'指定範囲の一覧を確認しました。詳報の作成とは別です。','partial':'一部の一覧を取得できていません。開示の取りこぼしにご注意ください。','failed':'日次一覧を取得できませんでした。以前の検知結果のみ保持しています。'}[state['state']]
    atomic_json(d/'earnings.json',state);return state

if __name__=='__main__':
    print(json.dumps({k:v for k,v in update_watch().items() if k!='items'},ensure_ascii=False))
