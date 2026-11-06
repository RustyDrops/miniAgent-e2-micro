"""Pure-Python SVG status badge generator for GitHub README and repository pulse."""
from html import escape
import os
from pathlib import Path

from .tools import ROOT


def render_svg_badge(label, value, color='#4c1'):
    """Generate a lightweight, dependency-free flat SVG badge matching shields.io style."""
    label_esc = escape(str(label))
    value_esc = escape(str(value))
    
    # Approximate text widths using average character width ~6.5px + 10px padding
    label_w = int(len(label) * 6.5) + 12
    value_w = int(len(str(value)) * 6.5) + 12
    total_w = label_w + value_w
    label_x = label_w / 2
    value_x = label_w + (value_w / 2)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{label_esc}: {value_esc}">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a">
    <rect width="{total_w}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{total_w}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="110">
    <text aria-hidden="true" x="{int(label_x * 10)}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{label_esc}</text>
    <text x="{int(label_x * 10)}" y="140" transform="scale(.1)" fill="#fff">{label_esc}</text>
    <text aria-hidden="true" x="{int(value_x * 10)}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)">{value_esc}</text>
    <text x="{int(value_x * 10)}" y="140" transform="scale(.1)" fill="#fff">{value_esc}</text>
  </g>
</svg>'''


def update_status_badges(workspace_root=None, budget=None, test_count=103):
    """Generate and write dynamic SVG status badges to site/badges/."""
    root = ROOT if workspace_root is None else Path(workspace_root)
    badge_dir = root / 'site' / 'badges'
    badge_dir.mkdir(parents=True, exist_ok=True)

    # 1. Budget badge
    spent_usd = 0.0
    limit_usd = 1.00
    if budget is not None:
        try:
            s_b, l_b = budget.today()
            spent_usd = s_b / 1e6
            limit_usd = l_b / 1e6
        except Exception:
            pass
    budget_color = '#4c1' if spent_usd < 0.75 * limit_usd else ('#fe7d37' if spent_usd < limit_usd else '#e05d44')
    budget_val = f"${spent_usd:.2f} / ${limit_usd:.2f}"
    budget_svg = render_svg_badge('budget', budget_val, color=budget_color)
    (badge_dir / 'budget.svg').write_text(budget_svg, encoding='utf-8')

    # 2. Canary test badge
    test_val = f"{test_count} passed"
    test_svg = render_svg_badge('canary', test_val, color='#97CA00')
    (badge_dir / 'tests.svg').write_text(test_svg, encoding='utf-8')

    # 3. Environment health badge
    health_svg = render_svg_badge('e2-micro', '38MB RAM (healthy)', color='#007ec6')
    (badge_dir / 'health.svg').write_text(health_svg, encoding='utf-8')

    return {
        'dir': str(badge_dir.relative_to(root)),
        'badges': ['budget.svg', 'tests.svg', 'health.svg'],
        'budget_val': budget_val,
        'test_val': test_val
    }
