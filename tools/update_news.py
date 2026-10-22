#!/usr/bin/env python3
"""Asa Brief 1.1: public headlines + fixed learning notes; no paid/LLM APIs.

Python 3.12 standard library only. Does not fetch article bodies, paid articles,
login pages, market prices, or generated prose. Source selection is a heuristic,
not fact checking. RSS 1.0/RDF, RSS 2.0 and Atom are supported.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
MAX_BYTES = 2_000_000
USER_AGENT = 'AsaBrief/1.1 (noncommercial headline reader; twice daily)'
CATS = ['日本経済','世界経済','金融政策','政治・地方自治','国際情勢','AI・産業','資産形成']

class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.blocked=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.blocked+=1
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.blocked=max(0,self.blocked-1)
    def handle_data(self, text):
        if not self.blocked:self.parts.append(text)

def clean(value: str, limit: int = 300) -> str:
    p=TextOnly();p.feed(unescape(value or ''))
    return re.sub(r'\s+', ' ',unescape(' '.join(p.parts))).strip()[:limit]

def host_ok(url: str, domains: list[str]) -> bool:
    try:
        p=urllib.parse.urlsplit(url)
        h=(p.hostname or '').lower().rstrip('.')
        return (p.scheme=='https' and p.username is None and p.password is None
                and p.port in (None,443) and any(h==d or h.endswith('.'+d) for d in domains))
    except ValueError:return False

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):self.hosts=hosts
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_ok(newurl,self.hosts):raise ValueError('redirect_outside_source')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(url: str, hosts: list[str]) -> bytes:
    if not host_ok(url,hosts):raise ValueError('source_url_not_allowed')
    request=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.5'})
    opener=urllib.request.build_opener(SafeRedirect(hosts))
    with opener.open(request,timeout=12) as response:
        if response.status!=200:raise ValueError('http_status_'+str(response.status))
        body=response.read(MAX_BYTES+1)
    if len(body)>MAX_BYTES:raise ValueError('feed_too_large')
    return body

class FeedLinks(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);url=a.get('href','')
        if tag in ('a','link') and (re.search(r'\.(?:xml|rdf)(?:[?#]|$)',url,re.I) or 'rss+xml' in a.get('type','') or 'atom+xml' in a.get('type','')):
            self.links.append(url)

def resolve_feed(feed:dict, downloader=download) -> str:
    if feed.get('query'):
        return 'https://news.google.com/rss/search?'+urllib.parse.urlencode({'q':feed['query'],'hl':'ja','gl':'JP','ceid':'JP:ja'})
    if feed.get('url'):return feed['url']
    page=feed['discovery_page'];p=FeedLinks()
    p.feed(downloader(page,feed['hosts']).decode('utf-8',errors='replace'))
    urls=[urllib.parse.urljoin(page,x) for x in p.links]
    urls=list(dict.fromkeys(u for u in urls if host_ok(u,feed['hosts']) and '/english/' not in u and '/en/' not in u))
    if not urls:raise ValueError('feed_link_missing')
    # For these official landing pages the Japanese new-release feed is first.
    return urls[0]

def local_name(tag):return tag.rsplit('}',1)[-1].lower()
def child(node,name):
    return next((x for x in node if local_name(x.tag)==name.lower()),None)
def child_text(node,*names):
    for name in names:
        n=child(node,name)
        if n is not None and n.text:return n.text.strip()
    return ''

def parse_date(s:str, default_zone=JST):
    if not s:return None
    try:d=parsedate_to_datetime(s)
    except (ValueError,TypeError,IndexError):
        try:d=datetime.fromisoformat(s.replace('Z','+00:00'))
        except ValueError:return None
    precision='date' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',s.strip()) else 'minute'
    if d.tzinfo is None:d=d.replace(tzinfo=default_zone)
    return d.astimezone(JST),precision

def parse_feed(blob:bytes, feed:dict, now:datetime, config:dict):
    if len(blob)>MAX_BYTES:raise ValueError('feed_too_large')
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)',blob,re.I):raise ValueError('xml_entities_disallowed')
    # XML libraries cannot parse every Japanese multi-byte encoding from bytes.
    match=re.search(br'<\?xml[^>]*encoding=["\']([^"\']+)',blob[:250],re.I)
    enc=match.group(1).decode('ascii') if match else 'utf-8-sig'
    try:txt=blob.decode(enc)
    except (UnicodeDecodeError,LookupError):raise ValueError('invalid_feed_encoding')
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)',txt,re.I):raise ValueError('xml_entities_disallowed')
    root=ET.fromstring(txt)
    if local_name(root.tag) not in ('rss','rdf','feed'):raise ValueError('not_an_rss_or_atom_feed')
    nodes=[e for e in root.iter() if local_name(e.tag) in ('item','entry')]
    out=[];dropped=Counter()
    for n in nodes:
        title=clean(child_text(n,'title'),260)
        url=child_text(n,'link')
        if not url:
            links=[x for x in n if local_name(x.tag)=='link' and x.attrib.get('rel','alternate')=='alternate']
            if links:url=links[0].attrib.get('href','')
        if url.startswith('/'):url=urllib.parse.urljoin(feed.get('url') or feed.get('discovery_page',''),url)
        date=parse_date(child_text(n,'pubdate','published','updated','date'),JST if feed.get('language')=='ja' else timezone.utc)
        if not title or not date:dropped['missing_title_or_date']+=1;continue
        published,precision=date
        max_age=config['primary_max_age_hours'] if feed['kind']=='primary' else config['press_max_age_hours']
        if published>now or published<now-timedelta(hours=max_age):dropped['out_of_time_window']+=1;continue
        if any(s in title for s in config['exclude_title_terms']):dropped['out_of_scope']+=1;continue
        source_name=feed['name'];publisher_url=feed.get('landing','');source_domain=feed['hosts'][0]
        if feed['kind']=='press_search':
            source=child(n,'source')
            publisher_url=source.attrib.get('url','') if source is not None else ''
            # Google RSS sometimes gives an http publisher home URL; no connection
            # is made to it. Validate the hostname using its https representation.
            if publisher_url.startswith('http://'):publisher_url='https://'+publisher_url[7:]
            if not host_ok(publisher_url,config['publisher_allowlist']):dropped['publisher_not_allowed']+=1;continue
            source_name=clean(source.text or '',70);source_domain=urllib.parse.urlsplit(publisher_url).hostname
            if not host_ok(url,['news.google.com']+config['publisher_allowlist']):dropped['link_not_allowed']+=1;continue
            if source_name and title.endswith(' - '+source_name):title=title[:-(len(source_name)+3)].strip()
        elif not host_ok(url,feed['hosts']):dropped['link_not_allowed']+=1;continue
        age=(now-published).total_seconds()/3600
        topical=any(t in title.lower() for t in ['政策','決算','金利','物価','賃金','財政','予算','関税','半導体','雇用','fomc','monetary'])
        score=max(0,30-age/5)+(12 if feed['kind']=='primary' else 0)+(6 if topical else 0)
        identifier=hashlib.sha256((url+'|'+title).encode()).hexdigest()[:20]
        out.append({'id':identifier,'cat':feed['category'],'tag':'公式発表' if feed['kind']=='primary' else '報道見出し',
         'date':published.strftime('%m/%d'),'published_at':published.isoformat(timespec='minutes'),'date_precision':precision,
         'title':title,'lead':('公式配信の見出しです。' if feed['kind']=='primary' else '報道機関の見出しです。')+'本文・正確な条件は出典を確認してください。',
         'source_url':url,'source_kind':feed['kind'],'publisher':source_name,'publisher_domain':source_domain,
         'language':feed.get('language','ja'),'sources':[{'name':source_name,'url':url}],
         'quality':'fixed_learning','age_label':'24時間以内' if age<=24 else ('48時間以内' if age<=48 else '直近7日の公式発表'),
         'read':3,'icon':{'日本経済':'📈','世界経済':'🌎','金融政策':'🏦','政治・地方自治':'🏛️','国際情勢':'🌍','AI・産業':'💻','資産形成':'💰'}[feed['category']],
         'tone':{'日本経済':'teal','世界経済':'violet','金融政策':'indigo','政治・地方自治':'blue','国際情勢':'amber','AI・産業':'slate','資産形成':'teal'}[feed['category']],
         '_score':score,'_titlekey':re.sub(r'[^\w]','',title.lower())})
    return out,dict(dropped)

def select_articles(items:list,config:dict):
    unique=[];seen_url=set();seen_title=set()
    for a in sorted(items,key=lambda x:(-x['_score'],x['id'])):
        if a['source_url'] in seen_url or a['_titlekey'] in seen_title:continue
        unique.append(a);seen_url.add(a['source_url']);seen_title.add(a['_titlekey'])
    chosen=[];ids=set();cats=Counter();publishers=Counter()
    def add(a):
        if a['id'] in ids or cats[a['cat']]>=config['max_per_category'] or publishers[a['publisher_domain']]>=config['max_per_publisher']:return False
        chosen.append(a);ids.add(a['id']);cats[a['cat']]+=1;publishers[a['publisher_domain']]+=1;return True
    # Reserve one available item per theme; never invent missing themes.
    for cat in CATS:
        for a in unique:
            if a['cat']==cat and add(a):break
    for a in unique:
        if len(chosen)>=config['max_articles']:break
        add(a)
    return sorted(chosen,key=lambda x:-x['_score'])

def enrich_with_fixed_notes(items,knowledge):
    topics=knowledge['topics']
    default={'日本経済':'company','世界経済':'world','金融政策':'rates','政治・地方自治':'local','国際情勢':'world','AI・産業':'tech','資産形成':'assets'}
    for a in items:
        matches=[(sum(word.lower() in a['title'].lower() for word in topic['keywords']),key) for key,topic in topics.items()]
        best=max(matches,key=lambda t:t[0])
        key=best[1] if best[0]>0 else default.get(a['cat'],'general');topic=topics[key]
        a['learning_topic']=topic['name'];a['learning_authored_on']=knowledge['authored_on']
        date=a['published_at'][:10] if a['date_precision']=='date' else a['published_at'].replace('T',' ').replace('+09:00',' JST')
        a['sections']=[['今回の取得範囲',f"{a['publisher']}が配信した見出し・リンク・公開日時（{date}）を取得しました。記事本文を読んだ要約ではなく、内容の独立した事実確認もしていません。"],
         ['基礎知識｜'+topic['name']+'（一般論）',topic['basics']],
         ['生活や投資とのつながり（一般論）',topic['mechanism']],
         ['元記事で確認したいこと',topic['checks']],
         ['解説の位置づけ','この解説はあらかじめ用意した学習ノートを見出しの語句に応じて選んだものです。今回のニュース固有の原因・影響を分析したものではありません。自動分類が合わないときは、元記事を優先してください。']]
        if a['language']=='en':a['sections'].insert(1,['英語の公式発表について','英語の見出しを原文のまま表示しています。日本語の基礎解説は翻訳ではありません。必要に応じてSafariなどの翻訳機能で原文を確認してください。'])
        a['glossary']=topic['glossary'];a['learning_sources']=topic['references']
        a.pop('_score',None);a.pop('_titlekey',None)
    return items

def collect(now,config,downloader=download):
    found=[];reports=[]
    for feed in config['feeds']:
        if not feed.get('enabled',True):continue
        try:
            url=resolve_feed(feed,downloader)
            items,dropped=parse_feed(downloader(url,feed['hosts']),feed,now,config)
            found.extend(items);reports.append({'name':feed['name'],'kind':feed['kind'],'ok':True,'eligible':len(items),'dropped':dropped})
        except (ValueError,KeyError,TimeoutError,ET.ParseError,OSError,urllib.error.URLError):
            # No raw responses, tokens or untrusted exception text enter public JSON.
            reports.append({'name':feed['name'],'kind':feed['kind'],'ok':False,'reason':'取得またはRSS解析に失敗'})
    return select_articles(found,config),reports

def atomic_json(path:Path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)

def run(now=None,downloader=download,data_dir=None,config=None,knowledge=None,dry_run=False):
    now=(now or datetime.now(JST)).astimezone(JST);data_dir=Path(data_dir or ROOT/'data')
    config=config or json.loads((ROOT/'config/sources.json').read_text(encoding='utf-8'))
    knowledge=knowledge or json.loads((ROOT/'config/knowledge.json').read_text(encoding='utf-8'))
    items,reports=collect(now,config,downloader);ok=sum(x['ok'] for x in reports)
    status={'attempted_at':now.isoformat(timespec='seconds'),'feeds_total':len(reports),'feeds_ok':ok,'feeds':reports,'state':'success' if ok==len(reports) else ('partial' if ok else 'failed')}
    if not ok:
        status['message']='全配信元の取得に失敗しました。最後に取得できた配信号を変更せず保持しています。'
        if not dry_run:atomic_json(data_dir/'status.json',status)
        raise RuntimeError(status['message'])
    items=enrich_with_fixed_notes(items,knowledge)
    previous=set()
    try:previous={a['id'] for a in json.loads((data_dir/'latest.json').read_text(encoding='utf-8')).get('articles',[])}
    except (FileNotFoundError,ValueError,KeyError):pass
    for a in items:a['new_since_last']=a['id'] not in previous
    status['message']='収集完了。' if status['state']=='success' else '一部の情報源を取得できませんでした。取得状況を確認してください。'
    data={'schema_version':1,'generated_at':now.isoformat(timespec='seconds'),'edition_date':now.date().isoformat(),
     'status':'live','editorial_mode':'no_api_fixed_learning','articles':items,'markets':[],'events':[],
     'notice':'API不使用。公式発表・許可リスト内の報道見出しと、固定の基礎解説です。本文の要約・独立した事実確認・個別の相場予測は行っていません。',
     'ranking_notice':'表示順は新しさ・分野・発表元などに基づく簡易ルールです。重要度や真偽の判定ではありません。',
     'feed_statistics':{'feed_count':len(reports),'feeds_ok':ok,'feeds_failed':len(reports)-ok},'source_reports':reports}
    if not dry_run:
        atomic_json(data_dir/'latest.json',data);atomic_json(data_dir/'status.json',status)
        atomic_json(data_dir/'archive'/f'{now.date().isoformat()}.json',data)
        archive=sorted((data_dir/'archive').glob('????-??-??.json'))
        for p in archive[:-14]:p.unlink()
        atomic_json(data_dir/'archive/index.json',{'dates':[p.stem for p in sorted((data_dir/'archive').glob('????-??-??.json'),reverse=True)]})
    return data

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dry-run',action='store_true');args=p.parse_args()
    try:
        result=run(dry_run=args.dry_run)
        print(json.dumps({'status':result['status'],'count':len(result['articles']),'mode':result['editorial_mode'],'date':result['edition_date'],'feeds':result['feed_statistics']},ensure_ascii=False))
    except RuntimeError as exc:
        print(str(exc),file=sys.stderr);sys.exit(2)
