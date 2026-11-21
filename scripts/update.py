#!/usr/bin/env python3
"""Fetch open AI feeds into a static JSON file; no paid API or secrets."""
from __future__ import annotations

import calendar
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'articles.json'

# Corporate research posts are not necessarily peer-reviewed papers.
# Anthropic feeds below are unofficial third-party RSS bridges.
FEEDS = [
    ('arXiv cs.AI', 'papers', 'https://rss.arxiv.org/rss/cs.AI', 'official'),
    ('arXiv cs.CL', 'papers', 'https://rss.arxiv.org/rss/cs.CL', 'official'),
    ('arXiv cs.IR', 'papers', 'https://rss.arxiv.org/rss/cs.IR', 'official'),
    ('arXiv cs.LG', 'papers', 'https://rss.arxiv.org/rss/cs.LG', 'official'),
    ('arXiv cs.CV', 'papers', 'https://rss.arxiv.org/rss/cs.CV', 'official'),
    ('Google Research', 'research', 'https://research.google/blog/rss/', 'official'),
    ('Microsoft Research', 'research', 'https://www.microsoft.com/en-us/research/blog/feed/', 'official'),
    ('Google DeepMind', 'research', 'https://deepmind.google/blog/rss.xml', 'official'),
    ('Anthropic Research', 'research', 'https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml', 'third-party'),
    ('Anthropic Engineering', 'research', 'https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml', 'third-party'),
    ('Claude Blog', 'news', 'https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_claude.xml', 'third-party'),
    ('OpenAI News', 'news', 'https://openai.com/news/rss.xml', 'official'),
]

TOPICS = [
    ('Agent', re.compile(r'\b(agentic|agents?|multi[- ]agent|tool[- ]use|tool[- ]calling|autonomous)\b', re.I)),
    ('RAG', re.compile(r'\b(rag|retrieval[- ]augmented|retrieval|retriever|vector database|knowledge graph|graph[- ]rag)\b', re.I)),
    ('LLM', re.compile(r'\b(llms?|large language models?|language models?|foundation models?|prompting|inference|reasoning|transformers?)\b', re.I)),
    ('多模态', re.compile(r'\b(multimodal|multi[- ]modal|vision[- ]language|visual question|vision language|image generation|text[- ]to[- ]image)\b', re.I)),
    ('视频生成', re.compile(r'\b(video generation|text[- ]to[- ]video|image[- ]to[- ]video|video diffusion|video synthesis|video models?)\b', re.I)),
    ('模型训练', re.compile(r'\b(fine[- ]tuning|post[- ]training|distillation|reinforcement learning|dpo|rlhf|grpo|pretraining|pre[- ]training|quantization|alignment|scaling laws?)\b', re.I)),
]
CLEAN_TAG = re.compile(r'<[^>]+>')
WS = re.compile(r'\s+')


def plain(text: object) -> str:
    return WS.sub(' ', html.unescape(CLEAN_TAG.sub(' ', str(text or '')))).strip()


def clean_url(url: str) -> str:
    try:
        p = urlsplit(url)
        if p.scheme not in ('https', 'http') or not p.netloc:
            return ''
        q = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith('utm_') and k.lower() not in ('ref', 'source')])
        return urlunsplit((p.scheme, p.netloc, p.path, q, ''))
    except Exception:
        return ''


def dedupe_key(url: str) -> str:
    m = re.search(r'(?:arxiv\.org/(?:abs|pdf)/|huggingface\.co/papers/)([0-9]{4}\.[0-9]{4,5}|[\w.-]+/\d{7})', url, re.I)
    if m:
        return 'arxiv:' + re.sub(r'v\d+$', '', m.group(1))
    return url


def get_tags(title: str, summary: str) -> list[str]:
    body = title + ' ' + summary[:1800]
    return [name for name, pattern in TOPICS if pattern.search(body)]


def published_iso(entry: dict) -> str:
    dt = entry.get('published_parsed') or entry.get('updated_parsed')
    if dt:
        return datetime.fromtimestamp(calendar.timegm(dt), timezone.utc).isoformat().replace('+00:00', 'Z')
    raw = entry.get('published') or entry.get('updated') or ''
    try:
        return datetime.fromisoformat(str(raw).replace('Z', '+00:00')).astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).date().isoformat() + 'T00:00:00Z'


def make_item(title: str, summary: str, url: str, *, source: str, group: str,
              date: str, pdf: str = '', origin: str = 'official') -> dict | None:
    title = plain(title)
    summary = plain(summary)[:3500]
    url = clean_url(url)
    if not title or not url:
        return None
    tags = get_tags(title, summary)
    # Preserve company announcements as well as keyword-matched research papers.
    if not tags and group == 'papers':
        return None
    doc_id = hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]
    return {'id': doc_id, 'title': title, 'summary': summary,
            'url': url, 'pdf': clean_url(pdf), 'source': source, 'group': group,
            'published': date, 'tags': tags, 'origin': origin}


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': 'AIResearchDesk/1.0 (public GitHub Pages reader)',
                      'Accept': 'application/rss+xml, application/atom+xml, application/json, application/xml, text/xml;q=0.8, */*;q=0.5'})
    adapter = HTTPAdapter(max_retries=Retry(total=2, connect=2, read=1, backoff_factor=1.5,
                                            status_forcelist=[429, 500, 502, 503, 504]))
    s.mount('https://', adapter)
    return s


def read_feed(s: requests.Session, source: str, group: str, url: str, origin: str) -> list[dict]:
    response = s.get(url, timeout=(10, 30))
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if not feed.entries and feed.bozo:
        raise ValueError('Invalid RSS/Atom XML')
    result = []
    for entry in feed.entries[:180]:
        title = entry.get('title', '')
        summary = entry.get('summary') or entry.get('description') or ''
        link = entry.get('link') or entry.get('id') or ''
        pdf = ''
        if group == 'papers':
            m = re.search(r'arxiv\.org/(?:abs|pdf)/([\w.\-/]+)', str(link))
            if m:
                arxiv_id = re.sub(r'v\d+$', '', m.group(1).removesuffix('.pdf'))
                link = 'https://arxiv.org/abs/' + arxiv_id
                pdf = 'https://arxiv.org/pdf/' + arxiv_id
        item = make_item(title, summary, link, source=source, group=group,
                         date=published_iso(entry), pdf=pdf, origin=origin)
        if item:
            result.append(item)
    return result


def read_hf(s: requests.Session) -> list[dict]:
    response = s.get('https://huggingface.co/api/daily_papers?limit=80',
                     headers={'Accept': 'application/json'}, timeout=(10, 30))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError('Hugging Face API returned non-list')
    result = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        p = row.get('paper', row)
        if not isinstance(p, dict):
            continue
        pid = str(p.get('id') or row.get('id') or '').strip()
        pid = re.sub(r'v\d+$', '', pid)
        if not re.fullmatch(r'(?:\d{4}\.\d{4,5}|[\w.-]+/\d{7})', pid):
            continue
        dt = str(row.get('publishedAt') or p.get('publishedAt') or row.get('createdAt') or p.get('published') or '')
        if not dt:
            dt = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        item = make_item(p.get('title', ''), p.get('summary',''),
                         'https://huggingface.co/papers/' + pid,
                         source='Hugging Face Daily Papers', group='papers',
                         date=dt, pdf='https://arxiv.org/pdf/' + pid, origin='official')
        if item:
            result.append(item)
    return result


def main() -> int:
    try:
        old = json.loads(DEST.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        old = {}
    previous = [x for x in old.get('articles', []) if isinstance(x, dict)]
    store = {dedupe_key(x['url']): x for x in previous if x.get('url') and x.get('title')}
    statuses = []
    succeeded = 0
    s = session()
    for src, group, url, origin in FEEDS:
        try:
            items = read_feed(s, src, group, url, origin)
            for x in items:
                store[dedupe_key(x['url'])] = x
            statuses.append({'source': src, 'ok': True, 'found': len(items)})
            succeeded += 1
            print(f'{src}: {len(items)} relevant entries')
        except (requests.RequestException, ValueError, TypeError) as e:
            statuses.append({'source': src, 'ok': False, 'error': type(e).__name__})
            print(f'WARN {src}: {e}', file=sys.stderr)
    try:
        items = read_hf(s)
        for x in items:
            store[dedupe_key(x['url'])] = x
        statuses.append({'source': 'Hugging Face Daily Papers', 'ok': True, 'found': len(items)})
        succeeded += 1
        print(f'Hugging Face: {len(items)} relevant entries')
    except (requests.RequestException, ValueError, TypeError) as e:
        statuses.append({'source': 'Hugging Face Daily Papers', 'ok': False, 'error': type(e).__name__})
        print(f'WARN Hugging Face: {e}', file=sys.stderr)
    if succeeded == 0:
        print('No sources were reachable; preserving previous data and failing this run', file=sys.stderr)
        return 1
    records = sorted(store.values(), key=lambda x: x.get('published') or '', reverse=True)
    kept = {'papers': 450, 'research': 260, 'news': 260}
    counters = {k:0 for k in kept}
    by_source = {}
    trimmed = []
    for x in records:
        g=x.get('group', 'news')
        src=x.get('source','')
        if g not in kept or counters[g]>=kept[g] or by_source.get(src, 0) >= 140:
            continue
        trimmed.append(x)
        counters[g]+=1
        by_source[src]=by_source.get(src, 0)+1
    output={'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'articles': trimmed, 'sources_status': statuses}
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Wrote {len(trimmed)} articles to {DEST}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
