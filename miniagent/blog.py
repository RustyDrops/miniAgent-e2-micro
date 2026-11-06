"""Render a small, self-contained static blog page from reviewed text drafts."""
from html import escape
from pathlib import Path


def build_page(title, description, posts):
    if not isinstance(title, str) or not title.strip() or len(title) > 80:
        raise ValueError('Title must be 1–80 characters')
    if not isinstance(description, str) or len(description) > 350:
        raise ValueError('Description must be at most 350 characters')
    if not isinstance(posts, list) or not 1 <= len(posts) <= 8:
        raise ValueError('Provide one to eight posts')
    items = []
    for name, content in posts:
        lines = content.strip().splitlines()
        if not lines:
            raise ValueError('Empty post')
        heading = lines[0].lstrip('# ').strip()[:120] or Path(name).stem
        body = '\n'.join(lines[1:]).strip()
        items.append('<article class="post"><div class="post-label">FIELD NOTE</div><h3>' +
                     escape(heading) + '</h3><div class="post-body">' + escape(body) + '</div></article>')
    # All agent-authored content is escaped; no external resources or scripts.
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>''' + escape(title) + '''</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#172c2b;background:#f4f3ed}*{box-sizing:border-box}
body{margin:0}a{color:inherit}header,main,footer{max-width:1080px;margin:auto;padding-left:24px;padding-right:24px}
.top{border-bottom:1px solid #d6ded5}.nav{min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{font-weight:760;letter-spacing:-.03em}.pill{color:#265e4c;font-size:.75rem;letter-spacing:.12em;text-transform:uppercase}
.hero{padding-top:88px;padding-bottom:86px;display:grid;grid-template-columns:2fr 1fr;gap:48px;align-items:end}
.eyebrow,.post-label{font-size:.72rem;font-weight:700;letter-spacing:.16em;color:#52796a}
h1{font-size:clamp(3rem,8vw,6.2rem);line-height:.98;letter-spacing:-.065em;margin:20px 0;overflow-wrap:anywhere}
.hero p{font-size:1.08rem;line-height:1.7;color:#506460;max-width:42rem}.aside{border-left:2px solid #a7c6a7;padding-left:20px;color:#506460;line-height:1.65}
.notes{border-top:1px solid #cbd7cd;padding-top:30px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:20px;margin-bottom:20px}
h2{font-size:1.8rem;letter-spacing:-.04em;margin:0}.count{color:#60756e;font-size:.85rem}
.post{padding:30px 0;border-top:1px solid #d6ded5;display:grid;grid-template-columns:160px 1fr;column-gap:32px}
.post h3{font-size:1.35rem;margin:0 0 14px;letter-spacing:-.025em;overflow-wrap:anywhere}.post-label{grid-row:span 2;padding-top:5px}
.post-body{grid-column:2;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.75;color:#415752}
footer{padding-top:60px;padding-bottom:36px;color:#667b73;font-size:.8rem}
@media(max-width:650px){.hero{grid-template-columns:1fr;padding-top:62px;padding-bottom:54px;gap:18px}.aside{max-width:34rem}.post{grid-template-columns:1fr;gap:12px}.post-label,.post-body{grid-column:1}.nav{min-height:64px}}
</style></head><body><div class="top"><header class="nav"><div class="brand">''' + escape(title) + '''</div><a class="pill" href="#notes">Field notes ↓</a></header></div>
<main><section class="hero"><div><div class="eyebrow">AN OPEN NOTEBOOK</div><h1>''' + escape(title) + '''</h1><p>''' + escape(description) + '''</p></div>
<div class="aside">A collection of research notes and experiments. Each entry is a starting point for further review.</div></section>
<section id="notes" class="notes"><div class="section-head"><h2>Latest notes</h2><span class="count">''' + str(len(items)) + ''' entries</span></div>''' + ''.join(items) + '''</section></main>
<footer>Built as a lightweight static page · Content should be reviewed before publication.</footer></body></html>'''
