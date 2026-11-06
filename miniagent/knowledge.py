"""Persistent, explicitly unverified learning notes; never executable skills."""
import json
import re
import sqlite3
from contextlib import closing
from uuid import uuid4


def _fts_db(directory):
    db_path = directory / 'index.db'
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id, topic, lesson, sources, tokenize="porter")')
    return conn


def remember(root, topic, lesson, sources):
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 100:
        raise ValueError('Topic must be 1–100 characters')
    if not isinstance(lesson, str) or not lesson.strip() or len(json.dumps(lesson, ensure_ascii=False).encode('utf-8')) > 700:
        raise ValueError('Lesson is too long')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2:
        raise ValueError('Provide one or two sources')
    if any(not isinstance(s, str) or len(s) > 250 or not re.fullmatch(r'https://[^\s<>"\']+', s) for s in sources):
        raise ValueError('Sources must be HTTPS URLs')
    directory = root / 'knowledge'
    directory.mkdir(parents=True, exist_ok=True)
    if len(list(directory.glob('*.json'))) >= 200:
        raise ValueError('Knowledge store is full')
    ident = uuid4().hex
    entry = {'id': ident, 'topic': topic.strip(), 'lesson': lesson.strip(), 'sources': sources,
             'status': 'unverified'}
    path = directory / (ident + '.json')
    # Exclusive creation avoids overwriting existing notes.
    with path.open('x', encoding='utf-8') as output:
        json.dump(entry, output, ensure_ascii=False)
    try:
        with closing(_fts_db(directory)) as conn:
            conn.execute('INSERT INTO notes_fts(id, topic, lesson, sources) VALUES(?,?,?,?)',
                         (ident, topic.strip(), lesson.strip(), json.dumps(sources)))
            conn.commit()
    except Exception:
        pass
    return ident


def search(root, query):
    if not isinstance(query, str) or len(query) > 120 or not query.strip():
        raise ValueError('Search requires a short query')
    directory = root / 'knowledge'
    # Fast path: Query SQLite FTS5 index if available
    try:
        db_path = directory / 'index.db'
        if db_path.is_file():
            clean_terms = [t for t in re.findall(r'\w+', query) if t]
            if clean_terms:
                fts_query = ' '.join(f'"{t}"*' for t in clean_terms[:6])
                with closing(_fts_db(directory)) as conn:
                    rows = conn.execute('SELECT id, topic FROM notes_fts WHERE notes_fts MATCH ? LIMIT 5', (fts_query,)).fetchall()
                    if rows:
                        return [{'id': r[0], 'topic': r[1], 'status': 'unverified'} for r in rows]
    except Exception:
        pass
    # Fallback path: Directory scan
    terms = [x.casefold() for x in query.split()[:8]]
    matches = []
    for path in sorted(directory.glob('*.json'))[:200]:
        if path.is_symlink() or path.stat().st_size > 5000:
            continue
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
            text = (entry.get('topic', '') + ' ' + entry.get('lesson', '')).casefold()
            if all(term in text for term in terms):
                matches.append({'id': entry['id'], 'topic': entry['topic'], 'status': 'unverified'})
        except (ValueError, TypeError, KeyError, OSError):
            continue
        if len(matches) >= 5:
            break
    return matches


def recall(root, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{32}', ident):
        raise ValueError('Invalid note ID')
    path = root / 'knowledge' / (ident + '.json')
    if path.is_symlink() or path.stat().st_size > 5000:
        raise ValueError('Invalid note')
    entry = json.loads(path.read_text(encoding='utf-8'))
    return {'topic': entry['topic'], 'lesson': entry['lesson'], 'sources': entry['sources'], 'status': 'unverified'}


def groom(root) -> dict:
    """Consolidate and remove duplicate or empty learning notes to maintain FTS5 precision."""
    directory = root / 'knowledge'
    if not directory.is_dir():
        return {'pruned': 0, 'total': 0}
    seen_topics = {}
    pruned = 0
    total = 0
    for path in sorted(directory.glob('*.json')):
        if path.is_symlink():
            continue
        total += 1
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
            topic_key = entry.get('topic', '').strip().lower()
            if not topic_key or topic_key in seen_topics:
                path.unlink(missing_ok=True)
                pruned += 1
            else:
                seen_topics[topic_key] = path.name
        except Exception:
            path.unlink(missing_ok=True)
            pruned += 1
    # Rebuild FTS5 index if notes were pruned
    if pruned > 0:
        try:
            db_path = directory / 'index.db'
            if db_path.is_file():
                db_path.unlink()
            with closing(_fts_db(directory)) as conn:
                for path in sorted(directory.glob('*.json')):
                    try:
                        entry = json.loads(path.read_text(encoding='utf-8'))
                        conn.execute('INSERT INTO notes_fts(id, topic, lesson, sources) VALUES(?,?,?,?)',
                                     (entry['id'], entry['topic'], entry['lesson'], json.dumps(entry.get('sources', []))))
                    except Exception:
                        pass
                conn.commit()
        except Exception:
            pass
    return {'pruned': pruned, 'remaining': total - pruned}

