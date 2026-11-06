"""Bounded public arXiv metadata search; returned text is untrusted."""
import re
import json
import threading
import time
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

_lock = threading.Lock()
_last_request = 0.0
ATOM = '{http://www.w3.org/2005/Atom}'
ARXIV_ID = r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d{1,3})?'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def clip(text, limit):
    while len(json.dumps(text, ensure_ascii=False).encode('utf-8')) > limit:
        text = text[:-1]
    return text


def fetch(params):
    global _last_request
    url = 'https://export.arxiv.org/api/query?' + urlencode(params)
    request = Request(url, headers={'User-Agent': 'MiniAgent/0.1 (personal research)', 'Accept': 'application/atom+xml'})
    # arXiv asks clients making sequential calls to leave three seconds between requests.
    with _lock:
        delay = 3.0 - (time.monotonic() - _last_request)
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(200001)
    if len(raw) > 200000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Invalid or oversized feed')
    return parse_feed(raw)


def parse_feed(raw):
    if len(raw) > 200000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Invalid or oversized feed')
    root = ET.fromstring(raw)
    if root.tag != ATOM + 'feed':
        raise ValueError('Invalid feed')
    papers = []
    for entry in root.findall(ATOM + 'entry')[:3]:
        link = (entry.findtext(ATOM + 'id') or '').strip()
        match = re.fullmatch(r'https?://arxiv\.org/abs/(' + ARXIV_ID + ')', link)
        if not match:
            continue
        paper_id = match.group(1)
        title = ' '.join((entry.findtext(ATOM + 'title') or '').split())[:180]
        abstract = ' '.join((entry.findtext(ATOM + 'summary') or '').split())[:12000]
        published = (entry.findtext(ATOM + 'published') or '')[:10]
        papers.append({'id': paper_id, 'title': title, 'abstract': abstract,
                       'published': published, 'url': 'https://arxiv.org/abs/' + paper_id})
    return papers


def search(query):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('Invalid query')
    terms = re.findall(r'[A-Za-z0-9]{2,40}', query)[:6]
    if not terms:
        raise ValueError('Query needs a search term')
    results = fetch({'search_query': ' AND '.join('all:' + term for term in terms), 'start': 0, 'max_results': 3})
    return [{'id': p['id'], 'title': clip(p['title'], 130), 'published': p['published'],
             'url': p['url'], 'abstract_excerpt': clip(p['abstract'][:180], 150)} for p in results]


def abstract(paper_id, offset=0):
    if not isinstance(paper_id, str) or not re.fullmatch(ARXIV_ID, paper_id):
        raise ValueError('Invalid arXiv identifier')
    if type(offset) is not int or not 0 <= offset <= 12000:
        raise ValueError('Invalid offset')
    papers = fetch({'id_list': paper_id, 'max_results': 1})
    if not papers:
        raise ValueError('Paper not found')
    paper = papers[0]
    # ID may be normalized to the latest version, but must refer to the same paper.
    if re.sub(r'v\d+$', '', paper['id']) != re.sub(r'v\d+$', '', paper_id):
        raise ValueError('Unexpected paper identifier')
    text = paper.pop('abstract')
    paper['title'] = clip(paper['title'], 180)
    chunk = clip(text[offset:offset + 400], 700)
    return {**paper, 'abstract_excerpt': chunk, 'offset': offset,
            'next_offset': offset + len(chunk) if offset + len(chunk) < len(text) else None}
