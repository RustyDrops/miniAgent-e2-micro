"""Small, bounded tools for research and producing reviewable local drafts."""
import ast
import base64
import difflib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import tokenize
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(os.environ.get('MINIAGENT_WORKSPACE', '/var/lib/miniagent/workspace')).resolve()
MAX_FILE = 20000


def schema(name, description, properties, required):
    return {'type': 'function', 'function': {'name': name, 'description': description,
        'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}}


SCHEMAS = [
    schema('system_health', 'Read bounded VM memory, disk, load and service resource limits; values may be unavailable.', {}, []),
    schema('search_wikipedia', 'Search Wikipedia for leads; verify important facts against primary sources.',
           {'query': {'type': 'string'}}, ['query']),
    schema('search_github', 'Search public GitHub repositories by keywords; returns descriptions and URLs.',
           {'query': {'type': 'string'}}, ['query']),
    schema('search_arxiv', 'Search arXiv technical papers by keywords; returns up to three titles, links, and short abstract excerpts.',
           {'query': {'type': 'string'}}, ['query']),
    schema('read_arxiv_abstract', 'Read a paged arXiv abstract by paper ID, e.g. 2301.00001. Abstracts may be preprints and are not full papers.',
           {'id': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['id']),
    schema('read_wikipedia', 'Read a short excerpt of a Wikipedia article by exact title; returns a citation URL and supports a character offset.',
           {'title': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['title']),
    schema('read_github_file', 'Read a UTF-8 file from a public GitHub repository default branch by owner/repository and file path; returns source URL and revision. Supports character offset.',
           {'repository': {'type': 'string'}, 'path': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['repository', 'path']),
    schema('list_drafts', 'List files in the local drafts workspace.', {}, []),
    schema('read_draft', 'Read a page of a UTF-8 draft, with SHA-256 and next character offset. Use the hash when editing.',
           {'path': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['path']),
    schema('write_draft', 'Create a new UTF-8 draft; fails if the file already exists. Never put credentials or private data in a draft.',
           {'path': {'type': 'string'}, 'content': {'type': 'string'}}, ['path', 'content']),
    schema('modify_draft', 'Append to a draft or replace one unique exact string. Supply SHA-256 from read_draft; fails if the content changed. One editor at a time.',
           {'path': {'type': 'string'}, 'expected_sha256': {'type': 'string'},
            'mode': {'type': 'string', 'enum': ['append', 'replace']}, 'content': {'type': 'string'},
            'find': {'type': 'string'}}, ['path', 'expected_sha256', 'mode', 'content']),
    schema('build_blog', 'Build a self-contained static blog draft at site/index.html from 1–8 existing text drafts. First line of each draft is its title. No publication occurs.',
           {'title': {'type': 'string'}, 'description': {'type': 'string'}, 'paths': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 8}}, ['title', 'description', 'paths']),
    schema('remember_learning', 'Save a sourced, unverified technical or agentic learning note for future work. This never installs code or changes instructions.',
           {'topic': {'type': 'string'}, 'lesson': {'type': 'string'}, 'sources': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 2}}, ['topic', 'lesson', 'sources']),
    schema('find_learning', 'Find previously saved unverified learning notes by keywords.', {'query': {'type': 'string'}}, ['query']),
    schema('recall_learning', 'Read a previously saved learning note by ID. Verify its claims before use.', {'id': {'type': 'string'}}, ['id']),
    schema('test_python_draft', 'Run a Python draft and its unittest script in the optional offline Linux sandbox. The draft is imported as subject. Disabled until sandbox is configured.',
           {'source_path': {'type': 'string'}, 'test_path': {'type': 'string'}}, ['source_path', 'test_path']),
    schema('propose_followup', 'During a recurring background task, propose one focused follow-up to run only after this task succeeds. Daily quota and budget checks apply; follow-ups cannot create further follow-ups.',
           {'task': {'type': 'string'}}, ['task']),
    schema('propose_question', 'Ask the user a clarifying question when requirements or decisions are ambiguous. Provide a concise question and context.',
           {'question': {'type': 'string'}, 'context': {'type': 'string'}}, ['question', 'context']),
    schema('check_python_syntax', 'Locally check Python draft syntax and indentation for free before running or testing. Returns valid or specific syntax error with line number.',
           {'path': {'type': 'string'}}, ['path']),
    schema('grep_draft', 'Search a draft file using a regex pattern or substring; returns matching line numbers and text snippets without loading the full file.',
           {'path': {'type': 'string'}, 'pattern': {'type': 'string'}, 'max_matches': {'type': 'integer', 'minimum': 1, 'maximum': 20}}, ['path', 'pattern']),
    schema('python_symbol_outline', 'Extract a lightweight outline of functions, classes, arguments, and docstrings from a Python draft using AST parsing (~50 tokens).',
           {'path': {'type': 'string'}}, ['path']),
    schema('draft_diff', 'Compute a unified diff between two drafts (e.g. before and after edits). Diffs are significantly smaller than full files.',
           {'old_path': {'type': 'string'}, 'new_path': {'type': 'string'}}, ['old_path', 'new_path']),
    schema('extract_markdown_toc', 'Extract a table of contents with heading levels and line numbers from a markdown draft (~30 tokens).',
           {'path': {'type': 'string'}}, ['path']),
    schema('check_url_validity', 'Perform a lightweight HTTP HEAD request to verify that a citation URL is reachable before using or saving it.',
           {'url': {'type': 'string'}}, ['url']),
    schema('python_import_check', 'Inspect imported modules in a Python draft and identify missing or non-standard third-party dependencies before running.',
           {'path': {'type': 'string'}}, ['path']),
    schema('draft_stats', 'Get line count, byte size, token estimate, and SHA-256 hash of a draft without loading its full text into context.',
           {'path': {'type': 'string'}}, ['path']),
    schema('strip_comments_and_docstrings', 'Strip comments and docstrings from Python code to minimize token size before inspection or reference.',
           {'path': {'type': 'string'}}, ['path']),
    schema('json_schema_validator', 'Deterministically validate whether a JSON string or object matches required keys at zero token cost.',
           {'text': {'type': 'string'}, 'required_keys': {'type': 'array', 'items': {'type': 'string'}}}, ['text', 'required_keys']),
    schema('web_search', 'Search the live web using TinySearch (free tier). Returns top ranked results with titles, snippets, and URLs.',
           {'query': {'type': 'string'}, 'location': {'type': 'string'}}, ['query']),
    schema('web_fetch', 'Fetch and extract clean markdown from a web page using TinyFetch (free tier). Excludes HTML boilerplate. Supports character offset paging.',
           {'url': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['url']),
    schema('inspect_task_history', 'Read execution history and logs for past tasks to self-heal and debug previous failures.',
           {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}, 'failed_only': {'type': 'boolean'}}, []),
    schema('estimate_token_cost', 'Deterministically calculate estimated token counts and costs for a given text or draft before sending to an LLM.',
           {'text': {'type': 'string'}, 'input_usd_per_million': {'type': 'number'}, 'output_usd_per_million': {'type': 'number'}}, ['text']),
    schema('ast_linter', 'Static AST analysis on a Python draft checking for common antipatterns (bare excepts, pass-only stubs) without running code.',
           {'path': {'type': 'string'}}, ['path']),
    schema('generate_test_scaffold', 'Generate an automated unittest.TestCase scaffold from a Python draft to implement TDD.',
           {'path': {'type': 'string'}, 'module_name': {'type': 'string'}}, ['path']),
    schema('canary_verify', 'Sequentially execute the offline test suite against candidate code to verify zero regressions before publishing.',
           {}, []),
    schema('groom_knowledge', 'Consolidate and remove duplicate learning notes from the knowledge base to keep FTS5 precision high.',
           {}, []),
    schema('generate_architecture_diagram', 'Generate a live Mermaid state flowchart of the active queue, budget, and specialist architecture.',
           {}, []),
    schema('generate_daily_journal', 'Compile an autonomous daily progress report (tasks, tool calls, costs, learnings, health) to updates/daily/YYYY-MM-DD.md.',
           {'date': {'type': 'string'}}, []),
    schema('generate_weekly_recap', 'Compile an autonomous weekly recap rollup of progress, budget pacing vs $7 limit, and learnings to updates/weekly/YYYY-Www.md.',
           {'week': {'type': 'string'}}, []),
]


def safe_path(name):
    if not isinstance(name, str) or not name or len(name) > 200:
        raise ValueError('Invalid path')
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    path = (ROOT / name).resolve()
    if path == ROOT or not path.is_relative_to(ROOT):
        raise ValueError('Path outside workspace')
    if any(part.startswith('.') for part in path.relative_to(ROOT).parts):
        raise ValueError('Hidden paths are not allowed')
    return path


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url):
    # Fixed hosts and paths, never a URL selected by the model.
    headers = {'User-Agent': 'MiniAgent/0.1 (personal research)', 'Accept': 'application/json'}
    if 'api.github.com' in url:
        headers['Accept'] = 'application/vnd.github+json'
        headers['X-GitHub-Api-Version'] = '2022-11-28'
        token = os.environ.get('MINIAGENT_GITHUB_TOKEN')
        if token and '\n' not in token and '\r' not in token:
            headers['Authorization'] = 'Bearer ' + token
    request = Request(url, headers=headers)
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(200001)
    if len(raw) > 200000:
        raise ValueError('Source response too large')
    return json.loads(raw)


def excerpt(text, offset):
    if type(offset) is not int or offset < 0 or offset > 100000:
        raise ValueError('Invalid offset')
    # Keep structured output intact under the agent's tool-result byte limit.
    chunk = text[offset:offset + 800]
    while len(json.dumps(chunk, ensure_ascii=False).encode('utf-8')) > 600:
        chunk = chunk[:-1]
    return {'excerpt': chunk, 'offset': offset, 'next_offset': offset + len(chunk) if offset + len(chunk) < len(text) else None}


def read_wikipedia(title, offset=0):
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError('Invalid title')
    params = urlencode({'action': 'query', 'prop': 'extracts', 'explaintext': 1,
                        'redirects': 1, 'titles': title, 'format': 'json', 'formatversion': 2})
    result = fetch_json('https://en.wikipedia.org/w/api.php?' + params)
    page = result['query']['pages'][0]
    if 'missing' in page or not isinstance(page.get('extract'), str):
        raise ValueError('Article not found')
    canonical = page['title']
    return {'source': 'https://en.wikipedia.org/wiki/' + quote(canonical.replace(' ', '_'), safe=''),
            'title': canonical, **excerpt(page['extract'], offset)}


def read_github_file(repo, path, offset=0):
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}', repo) or '..' in repo:
        raise ValueError('Invalid repository')
    if not isinstance(path, str) or len(path) > 160 or not re.fullmatch(r'[A-Za-z0-9_./-]+', path) or any(part in ('', '.', '..') or part.startswith('.') for part in path.split('/')):
        raise ValueError('Invalid repository path')
    # The API is unauthenticated and the endpoint is constructed locally; private
    # repository credentials and arbitrary URLs are never supplied to a model.
    result = fetch_json('https://api.github.com/repos/' + repo + '/contents/' + quote(path, safe='/'))
    if result.get('type') != 'file' or result.get('encoding') != 'base64':
        raise ValueError('Expected a public text file')
    content = base64.b64decode(result['content'], validate=False)
    if len(content) > 100000:
        raise ValueError('Source file too large')
    text = content.decode('utf-8')
    sha = result.get('sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid file revision')
    # Blob URL is immutable; derive it rather than trusting response URLs.
    return {'source': 'https://api.github.com/repos/' + repo + '/git/blobs/' + sha,
            'view': 'https://github.com/' + repo + '/blob/HEAD/' + quote(path, safe='/'),
            'path': path, 'blob_sha': sha, **excerpt(text, offset)}


def check_python_syntax(path):
    target = safe_path(path)
    raw = target.read_bytes()
    try:
        ast.parse(raw.decode('utf-8'), filename=target.name)
        return {'path': str(target.relative_to(ROOT)), 'status': 'valid_syntax'}
    except SyntaxError as exc:
        return {'path': str(target.relative_to(ROOT)), 'status': 'syntax_error',
                'line': exc.lineno, 'offset': exc.offset, 'msg': exc.msg,
                'snippet': (exc.text or '').strip()[:100]}


def grep_draft(path, pattern, max_matches=10):
    target = safe_path(path)
    text = target.read_text(encoding='utf-8')
    if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
        raise ValueError('Invalid search pattern')
    regex = re.compile(pattern, re.IGNORECASE)
    matches = []
    for i, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            matches.append({'line': i, 'text': line[:150]})
            if len(matches) >= max_matches:
                break
    return {'path': str(target.relative_to(ROOT)), 'matches': matches, 'count': len(matches)}


def python_symbol_outline(path):
    target = safe_path(path)
    text = target.read_text(encoding='utf-8')
    tree = ast.parse(text, filename=target.name)
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            doc = ast.get_docstring(node)
            symbols.append({'type': 'function', 'name': node.name, 'line': node.lineno,
                            'args': args, 'doc': doc[:80] if doc else None})
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            doc = ast.get_docstring(node)
            symbols.append({'type': 'class', 'name': node.name, 'line': node.lineno,
                            'methods': methods, 'doc': doc[:80] if doc else None})
    return {'path': str(target.relative_to(ROOT)), 'symbols': symbols[:25]}


def draft_diff(old_path, new_path):
    p1 = safe_path(old_path)
    p2 = safe_path(new_path)
    lines1 = p1.read_text(encoding='utf-8').splitlines(keepends=True)
    lines2 = p2.read_text(encoding='utf-8').splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, fromfile=old_path, tofile=new_path, n=3))
    text = ''.join(diff)[:1600]
    return text if text.strip() else 'No differences.'


def extract_markdown_toc(path):
    target = safe_path(path)
    text = target.read_text(encoding='utf-8')
    toc = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        m = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if m:
            toc.append({'level': len(m.group(1)), 'heading': m.group(2).strip()[:100], 'line': line_no})
    return {'path': str(target.relative_to(ROOT)), 'headings': toc[:30]}


def check_url_validity(url):
    if not isinstance(url, str) or not re.fullmatch(r'https://[^\s<>"\']+', url) or len(url) > 250:
        raise ValueError('Must be a valid HTTPS URL')
    req = Request(url, headers={'User-Agent': 'MiniAgent/0.1 (link-check)'}, method='HEAD')
    try:
        with build_opener(NoRedirect()).open(req, timeout=3) as resp:
            code = getattr(resp, 'status', 200)
            return {'url': url, 'valid': True, 'http_code': code}
    except Exception as exc:
        code = getattr(exc, 'code', None)
        return {'url': url, 'valid': False, 'http_code': code, 'error': type(exc).__name__}


def python_import_check(path):
    target = safe_path(path)
    text = target.read_text(encoding='utf-8')
    tree = ast.parse(text, filename=target.name)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                modules.add(n.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split('.')[0])
    stdlib = set(getattr(sys, 'stdlib_module_names', set(sys.builtin_module_names))) | set(sys.builtin_module_names) | {'subject', target.stem}
    missing = [m for m in sorted(modules) if m not in stdlib and not (target.parent / f'{m}.py').is_file()]
    return {'path': str(target.relative_to(ROOT)), 'imports': sorted(modules), 'third_party_or_missing': missing}


def draft_stats(path):
    target = safe_path(path)
    raw = target.read_bytes()
    lines = raw.count(b'\n') + (1 if raw and not raw.endswith(b'\n') else 0)
    return {'path': str(target.relative_to(ROOT)), 'bytes': len(raw), 'lines': lines,
            'estimated_tokens': len(raw) // 4, 'sha256': hashlib.sha256(raw).hexdigest()}


def strip_comments_and_docstrings(path):
    target = safe_path(path)
    source = target.read_text(encoding='utf-8')
    io_obj = io.StringIO(source)
    out = []
    last_lineno = -1
    last_col = 0
    tokgen = tokenize.generate_tokens(io_obj.readline)
    for toktype, ttext, (slineno, scol), (elineno, ecol), ltext in tokgen:
        if slineno > last_lineno:
            last_col = 0
        if scol > last_col:
            out.append(' ' * (scol - last_col))
        if toktype != tokenize.COMMENT:
            out.append(ttext)
        last_lineno = elineno
        last_col = ecol
    cleaned = ''.join(out)
    lines = [line for line in cleaned.splitlines() if line.strip()]
    return '\n'.join(lines)[:2000]


def json_schema_validator(text, required_keys):
    if not isinstance(required_keys, list):
        raise ValueError('required_keys must be a list')
    try:
        data = json.loads(text) if isinstance(text, str) else text
        if not isinstance(data, dict):
            return {'valid': False, 'error': 'Root must be a JSON object'}
        missing = [k for k in required_keys if k not in data]
        return {'valid': len(missing) == 0, 'missing_keys': missing, 'keys_found': list(data.keys())}
    except Exception as exc:
        return {'valid': False, 'error': f'Invalid JSON: {exc}'}


LOW_SIGNAL_DOMAINS = {
    'youtube.com', 'youtu.be', 'facebook.com', 'fb.com', 'tiktok.com',
    'instagram.com', 'twitter.com', 'x.com', 'reddit.com'
}


def tiny_search(query, location='US'):
    key = os.environ.get('TINYFISH_API_KEY', '').strip()
    if not key:
        return {'error': 'TinyFish API key not configured. Set TINYFISH_API_KEY to enable live web search.'}
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ValueError('Invalid search query')
    params = urlencode({'query': query.strip(), 'location': str(location)[:10]})
    req = Request(f'https://api.search.tinyfish.ai?{params}', headers={'X-API-Key': key, 'Accept': 'application/json'})
    with build_opener(NoRedirect()).open(req, timeout=10) as resp:
        raw = resp.read(100000)
    data = json.loads(raw)
    raw_results = data.get('results', [])
    filtered = []
    for item in raw_results:
        url = item.get('url', '')
        host = (url.split('://', 1)[-1].split('/', 1)[0]).lower().replace('www.', '')
        if any(host == d or host.endswith('.' + d) for d in LOW_SIGNAL_DOMAINS) and not any(d.split('.')[0] in query.lower() for d in LOW_SIGNAL_DOMAINS):
            continue
        filtered.append({
            'title': (item.get('title') or '')[:100],
            'snippet': (item.get('snippet') or '')[:200],
            'url': url
        })
        if len(filtered) >= 5:
            break
    return {'query': query, 'count': len(filtered), 'results': filtered}


def tiny_fetch(url, offset=0):
    key = os.environ.get('TINYFISH_API_KEY', '').strip()
    if not key:
        return {'error': 'TinyFish API key not configured. Set TINYFISH_API_KEY to enable live web fetch.'}
    if not isinstance(url, str) or not re.fullmatch(r'https://[^\s<>"\']+', url) or len(url) > 250:
        raise ValueError('Must be a valid HTTPS URL')
    payload = json.dumps({'urls': [url], 'format': 'markdown', 'links': False, 'per_url_timeout_ms': 15000}).encode('utf-8')
    req = Request('https://api.fetch.tinyfish.ai', data=payload,
                  headers={'X-API-Key': key, 'Content-Type': 'application/json', 'Accept': 'application/json'},
                  method='POST')
    with build_opener(NoRedirect()).open(req, timeout=20) as resp:
        raw = resp.read(200000)
    data = json.loads(raw)
    results = data.get('results', [])
    if not results:
        errors = data.get('errors', [])
        err_msg = errors[0].get('error', 'Unknown fetch error') if errors else 'No content returned'
        return {'url': url, 'error': err_msg}
    first = results[0]
    text = (first.get('text') or '').strip()
    title = (first.get('title') or '').strip()
    return {'source': url, 'title': title, **excerpt(text, offset)}


def inspect_task_history(limit=5, failed_only=False):
    db_path = os.environ.get('MINIAGENT_DB', 'miniagent.db')
    try:
        from .queue import Queue
        q = Queue(db_path)
        history = q.get_history(limit=min(max(1, limit), 20), failed_only=bool(failed_only))
        return [{
            'job_id': h[1], 'task': h[2][:100], 'origin': h[3], 'state': h[4],
            'duration_ms': h[7], 'result_excerpt': (h[8] or '')[:150],
            'tool_calls': h[9], 'error_type': h[10]
        } for h in history]
    except Exception as exc:
        return {'history': [], 'note': f'Task history unavailable ({type(exc).__name__})'}


def estimate_token_cost(text, input_usd_per_million=0.10, output_usd_per_million=0.20):
    if not isinstance(text, str):
        raise ValueError('Text must be a string')
    raw_bytes = len(text.encode('utf-8'))
    tokens = max(1, raw_bytes // 4)
    in_cost = (tokens / 1_000_000) * float(input_usd_per_million)
    out_cost = (tokens / 1_000_000) * float(output_usd_per_million)
    return {
        'bytes': raw_bytes,
        'estimated_tokens': tokens,
        'input_cost_usd': round(in_cost, 6),
        'output_cost_usd': round(out_cost, 6)
    }


def ast_linter(path):
    target = safe_path(path)
    text = target.read_text(encoding='utf-8')
    try:
        tree = ast.parse(text, filename=target.name)
    except SyntaxError as exc:
        return {'path': str(target.relative_to(ROOT)), 'status': 'syntax_error', 'line': exc.lineno, 'error': exc.msg}
    
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append({'line': node.lineno, 'type': 'bare_except', 'message': 'Avoid bare except without exception class.'})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                issues.append({'line': node.lineno, 'type': 'stub_function', 'message': f'Function {node.name} only contains pass.'})
    return {'path': str(target.relative_to(ROOT)), 'status': 'clean' if not issues else 'warnings_found', 'issues': issues[:10]}


def _handle_inner(name, args):
    try:
        if name == 'system_health':
            from .health import collect
            return json.dumps(collect(ROOT))
        if name in ('search_arxiv', 'read_arxiv_abstract'):
            from . import research
            result = research.search(args['query']) if name == 'search_arxiv' else research.abstract(args['id'], args.get('offset', 0))
            return json.dumps(result, ensure_ascii=False)
        if name in ('search_wikipedia', 'search_github'):
            query = args['query'].strip()[:200]
            if not query:
                raise ValueError('Query is empty')
            if name == 'search_wikipedia':
                params = urlencode({'action': 'query', 'list': 'search', 'srsearch': query, 'srlimit': 5, 'format': 'json'})
                result = fetch_json('https://en.wikipedia.org/w/api.php?' + params)
                return json.dumps([{'title': x['title'], 'url': 'https://en.wikipedia.org/wiki/' + quote(x['title'].replace(' ', '_'))} for x in result['query']['search']])
            result = fetch_json('https://api.github.com/search/repositories?' + urlencode({'q': query, 'per_page': 5}))
            return json.dumps([{'name': x['full_name'], 'url': x['html_url'], 'description': x['description']} for x in result['items']])
        if name == 'read_wikipedia':
            return json.dumps(read_wikipedia(args['title'], args.get('offset', 0)), ensure_ascii=False)
        if name == 'read_github_file':
            return json.dumps(read_github_file(args['repository'], args['path'], args.get('offset', 0)), ensure_ascii=False)
        if name == 'test_python_draft':
            from .sandbox import run_python_tests
            try:
                return json.dumps(run_python_tests(safe_path(args['source_path']), safe_path(args['test_path'])), ensure_ascii=False)
            except RuntimeError as exc:
                return 'Sandbox unavailable: ' + str(exc)
        if name in ('remember_learning', 'find_learning', 'recall_learning'):
            try:
                ROOT.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            from . import knowledge
            # Do not follow a substituted knowledge directory outside the workspace.
            if (ROOT / 'knowledge').resolve() != ROOT / 'knowledge':
                raise ValueError('Invalid knowledge directory')
            if name == 'remember_learning':
                ident = knowledge.remember(ROOT, args['topic'], args['lesson'], args['sources'])
                return 'Saved unverified learning note: ' + ident
            if name == 'find_learning':
                return json.dumps(knowledge.search(ROOT, args['query']), ensure_ascii=False)
            return json.dumps(knowledge.recall(ROOT, args['id']), ensure_ascii=False)
        if name == 'build_blog':
            from .blog import build_page
            paths = args['paths']
            if not isinstance(paths, list) or not 1 <= len(paths) <= 8:
                raise ValueError('Provide one to eight drafts')
            posts = []
            for name in paths:
                path = safe_path(name)
                if path.stat().st_size > 8000:
                    raise ValueError('Post too large')
                posts.append((name, path.read_text(encoding='utf-8')))
            page = build_page(args['title'], args['description'], posts)
            if len(page.encode('utf-8')) > MAX_FILE:
                raise ValueError('Page too large to publish as a draft')
            output = safe_path('site/index.html')
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(page, encoding='utf-8')
            return 'Blog draft saved: site/index.html. Review with /preview site/index.html before publishing.'
        if name == 'list_drafts':
            return json.dumps([str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and not p.is_symlink() and all(not part.startswith('.') for part in p.relative_to(ROOT).parts)][:100])
        if name == 'read_draft':
            path = safe_path(args['path'])
            if path.stat().st_size > MAX_FILE:
                raise ValueError('File too large')
            raw = path.read_bytes()
            if len(raw) > MAX_FILE:
                raise ValueError('File too large')
            return json.dumps({'path': args['path'], 'sha256': hashlib.sha256(raw).hexdigest(),
                               **excerpt(raw.decode('utf-8'), args.get('offset', 0))}, ensure_ascii=False)
        if name == 'write_draft':
            path = safe_path(args['path'])
            content = args['content']
            if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_FILE:
                raise ValueError('Draft too large')
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as output:
                output.write(content.encode('utf-8'))
            return 'Draft created: ' + str(path.relative_to(ROOT))
        if name == 'modify_draft':
            path = safe_path(args['path'])
            raw = path.read_bytes()
            if len(raw) > MAX_FILE:
                raise ValueError('Draft too large')
            expected = args['expected_sha256']
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or hashlib.sha256(raw).hexdigest() != expected:
                return 'Edit rejected: draft changed; read it again.'
            original = raw.decode('utf-8')
            content = args['content']
            if not isinstance(content, str):
                raise ValueError('Content must be text')
            if args['mode'] == 'append':
                updated = original + content
            elif args['mode'] == 'replace':
                find = args.get('find')
                if not isinstance(find, str) or not find or original.count(find) != 1:
                    return 'Edit rejected: find text must match exactly once.'
                updated = original.replace(find, content, 1)
            else:
                raise ValueError('Unknown edit mode')
            result = updated.encode('utf-8')
            if len(result) > MAX_FILE:
                raise ValueError('Draft too large')
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.miniagent-', delete=False) as temp:
                    temp_name = temp.name
                    temp.write(result)
                if path.read_bytes() != raw:
                    return 'Edit rejected: draft changed; read it again.'
                os.replace(temp_name, path)
                temp_name = None
            finally:
                if temp_name is not None:
                    os.unlink(temp_name)
            return json.dumps({'path': args['path'], 'sha256': hashlib.sha256(result).hexdigest(), 'bytes': len(result)})
        if name == 'check_python_syntax':
            return json.dumps(check_python_syntax(args['path']))
        if name == 'grep_draft':
            return json.dumps(grep_draft(args['path'], args['pattern'], min(args.get('max_matches', 10), 20)))
        if name == 'python_symbol_outline':
            return json.dumps(python_symbol_outline(args['path']))
        if name == 'draft_diff':
            return draft_diff(args['old_path'], args['new_path'])
        if name == 'extract_markdown_toc':
            return json.dumps(extract_markdown_toc(args['path']))
        if name == 'check_url_validity':
            return json.dumps(check_url_validity(args['url']))
        if name == 'python_import_check':
            return json.dumps(python_import_check(args['path']))
        if name == 'draft_stats':
            return json.dumps(draft_stats(args['path']))
        if name == 'strip_comments_and_docstrings':
            return strip_comments_and_docstrings(args['path'])
        if name == 'json_schema_validator':
            return json.dumps(json_schema_validator(args['text'], args['required_keys']))
        if name == 'web_search':
            return json.dumps(tiny_search(args['query'], args.get('location', 'US')), ensure_ascii=False)
        if name == 'web_fetch':
            return json.dumps(tiny_fetch(args['url'], args.get('offset', 0)), ensure_ascii=False)
        if name == 'inspect_task_history':
            return json.dumps(inspect_task_history(args.get('limit', 5), args.get('failed_only', False)), ensure_ascii=False)
        if name == 'estimate_token_cost':
            return json.dumps(estimate_token_cost(args['text'], args.get('input_usd_per_million', 0.10), args.get('output_usd_per_million', 0.20)), ensure_ascii=False)
        if name == 'ast_linter':
            return json.dumps(ast_linter(args['path']), ensure_ascii=False)
        if name == 'generate_test_scaffold':
            from .test_generator import generate_test_scaffold
            target = safe_path(args['path'])
            code = target.read_text(encoding='utf-8')
            mod_name = args.get('module_name', target.stem)
            return generate_test_scaffold(code, mod_name)
        if name == 'canary_verify':
            from .canary import run_canary_tests
            return json.dumps(run_canary_tests(), ensure_ascii=False)
        if name == 'groom_knowledge':
            from . import knowledge
            return json.dumps(knowledge.groom(ROOT), ensure_ascii=False)
        if name == 'generate_architecture_diagram':
            from decimal import Decimal
            from .diagram import generate_mermaid_diagram
            from .queue import Queue
            from .budget import Budget
            db_p = os.environ.get('MINIAGENT_DB', 'miniagent.db')
            q = Queue(db_p)
            daily_usd = Decimal(os.environ.get('MINIAGENT_DAILY_USD', '0.50'))
            b = Budget(db_p, daily_usd)
            return generate_mermaid_diagram(q, b)
        if name == 'generate_daily_journal':
            from decimal import Decimal
            from .queue import Queue
            from .budget import Budget
            from .journal import generate_daily_journal
            db_p = os.environ.get('MINIAGENT_DB', 'miniagent.db')
            q = Queue(db_p)
            daily_usd = Decimal(os.environ.get('MINIAGENT_DAILY_USD', '0.50'))
            b = Budget(db_p, daily_usd)
            return json.dumps(generate_daily_journal(q, ROOT, date_str=args.get('date'), budget=b), ensure_ascii=False)
        if name == 'generate_weekly_recap':
            from decimal import Decimal
            from .queue import Queue
            from .budget import Budget
            from .journal import generate_weekly_recap
            db_p = os.environ.get('MINIAGENT_DB', 'miniagent.db')
            q = Queue(db_p)
            daily_usd = Decimal(os.environ.get('MINIAGENT_DAILY_USD', '0.50'))
            b = Budget(db_p, daily_usd)
            return json.dumps(generate_weekly_recap(q, ROOT, week_str=args.get('week'), budget=b), ensure_ascii=False)
        raise ValueError('Unknown tool')
    except Exception as exc:
        return 'Tool failed: ' + type(exc).__name__


def handle(name, args):
    cache_eligible = name in ('check_python_syntax', 'python_symbol_outline', 'grep_draft',
                              'draft_stats', 'extract_markdown_toc', 'ast_linter', 'web_search', 'estimate_token_cost')
    cache = None
    target_sha = ''
    if cache_eligible:
        try:
            from .cache import ToolCache
            db_p = os.environ.get('MINIAGENT_DB', 'miniagent.db')
            cache = ToolCache(db_p)
            if 'path' in args:
                try:
                    target_sha = hashlib.sha256(safe_path(args['path']).read_bytes()).hexdigest()
                except Exception:
                    pass
            cached = cache.get(name, args, target_sha)
            if cached is not None:
                return cached
        except Exception:
            pass

    result = _handle_inner(name, args)
    if cache and result and not result.startswith('Tool failed:'):
        try:
            cache.put(name, args, result, target_sha=target_sha)
        except Exception:
            pass
    return result
