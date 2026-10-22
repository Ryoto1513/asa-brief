"""Deterministic editorial selection. Scores are relevance heuristics, not fact checks."""
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

CATEGORIES=['日本経済','決算','金融政策','世界経済','国際情勢','セキュリティ','AI・産業','政治・地方自治','社会・重要','資産形成']
NOISE=re.compile(r'職員.{0,12}募集|採用[試情予]|採用[,、：:]|非常勤|入札公告|落札|調達情報|委員会.{0,20}(配布資料|議事録|開催)|主査ヒアリング|セミナー.{0,10}(開催|参加)|人事異動|読者プレゼント|占い|芸能|交際報道|週間レポート|Weekly Report',re.I)
NOISE_PATH=re.compile(r'/(recruit|saiyou|saiyo|procurement|chotatsu|nyusatsu)/',re.I)
EARNINGS=re.compile(r'決算|業績予想|上方修正|下方修正|増益|減益|営業利益|純利益|増配|自社株買い')
SECURITY=re.compile(r'脆弱性|サイバー攻撃|ランサム|情報漏[洩え]|不正アクセス|ゼロデイ|security advis|remote code execution|critical vulnerabil|CVE-\d{4}',re.I)
SEC_HIGH=re.compile(r'重大|緊急|悪用|大規模|任意のコード|認証不要|PHP|Windows|Chrome|iPhone|OpenSSL|WordPress|critical|remote code|zero.day',re.I)
SOCIAL=re.compile(r'暴動|夜間外出禁止|大規模.{0,8}(デモ|抗議|停電|障害)|非常事態|緊急事態|津波|避難指示|特別警報|大地震|大規模災害|感染拡大|curfew|riots',re.I)
MACRO=re.compile(r'日銀|FRB|FOMC|政策金利|利上げ|利下げ|物価|消費者物価|賃金|雇用統計|GDP|円相場|円安|円高|原油|関税|国債|景気|金融政策',re.I)
INVEST=re.compile(r'半導体|データセンター|設備投資|生成AI|受注|株主還元|小型株|成長株|日本株|業績|決算|株式|AI|NISA|資産形成|投資信託',re.I)
PUBLIC=re.compile(r'予算|税制|給付|防災|治水|水害|内水氾濫|上下水道|インフラ|公共料金|社会保険|年金|選挙|外交|停戦|制裁')

def classify(a):
    title=a['title'];url=a.get('source_url','')
    if NOISE.search(title) or NOISE_PATH.search(urlsplit(url).path):return None
    cat=a.get('cat','社会・重要');score=0;reason=''
    if SECURITY.search(title):
        if not SEC_HIGH.search(title):return None
        cat='セキュリティ';score=65;reason='利用サービスや開発環境の安全に関わる重要情報'
    elif SOCIAL.search(title):
        cat='国際情勢' if re.search(r'パリ|フランス|欧州|海外|米国|Paris|France',title,re.I) else '社会・重要'
        score=62;reason='社会への影響が大きく、知っておきたい動き'
    elif EARNINGS.search(title):
        # Only official constituent matching may set nikkei225=True.
        cat='決算' if a.get('nikkei225') else '日本経済';score=60;reason='企業の業績・見通し・株主還元に関わる'
    elif MACRO.search(title):score=52;reason='金利・為替・景気を通じて投資と生活に関わる'
    elif INVEST.search(title):score=43;reason='日本株と成長産業の変化を追う'
    elif PUBLIC.search(title):score=38;reason='家計・地域の政策・防災への影響を確認'
    elif cat in ('国際情勢','世界経済') and a.get('source_kind')=='press_search':score=29;reason='日本以外の重要な経済・社会動向'
    else:return None
    # Official status is a small bonus, not a license to promote administrative notices.
    score+=6 if a.get('source_kind')=='primary' else 0
    score+=min(12,max(0,a.get('_score',0)/4))
    return cat,score,reason

def event_key(a):
    """Conservative repeated-event grouping for explicit CVEs; no vague LLM clustering."""
    cves=re.findall(r'CVE-\d{4}-\d+',a['title'],re.I)
    if cves:return 'cve:'+min(x.upper() for x in cves)
    if re.search(r'PHP',a['title'],re.I) and SECURITY.search(a['title']):return 'php-security:'+a.get('date','')
    return None

def select(items,config):
    ranked=[]
    for a in items:
        decision=classify(a)
        if not decision:continue
        cat,score,reason=decision
        a=dict(a,cat=cat,_score=score,selection_reason=reason)
        ranked.append(a)
    ranked.sort(key=lambda a:(-a['_score'],a['id']))
    chosen=[];counts={};pubs={};keys=set();urls=set();candidates=[]
    for a in ranked:
        key=event_key(a)
        norm=re.sub(r'\W','',a['title'])
        if a['source_url'] in urls or key and key in keys:continue
        if any(SequenceMatcher(None,norm,t).ratio()>.88 for t in candidates):continue
        if counts.get(a['cat'],0)>=config.get('max_per_category',4):continue
        if pubs.get(a['publisher_domain'],0)>=config.get('max_per_publisher',4):continue
        chosen.append(a);urls.add(a['source_url']);candidates.append(norm)
        if key:keys.add(key)
        counts[a['cat']]=counts.get(a['cat'],0)+1;pubs[a['publisher_domain']]=pubs.get(a['publisher_domain'],0)+1
        if len(chosen)>=config.get('max_articles',15):break
    return chosen
