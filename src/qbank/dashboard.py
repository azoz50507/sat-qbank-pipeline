"""Review dashboard (Phase 3).

A small local Flask app for reviewing rendering & routing results: stat
tiles, per-source classification distribution, a filterable thumbnail grid,
and a per-page quality card (stats + routing reason + extracted text).

Read-only over ``data/registry/sources.db`` (``pages`` table) and the
rendered assets in ``data/pages/``. Binds to 127.0.0.1 only: pages from
RESTRICTED sources are shown for internal review and must not be published.

Usage:
    python src/qbank/dashboard.py          # http://127.0.0.1:8765
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, abort, render_template_string, request, send_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
PAGES_DIR = PROJECT_ROOT / "data" / "pages"

PER_PAGE = 48
CLASSES = ["content", "answer_key", "cover", "index", "blank"]
ROUTES = ["text", "image", "skip"]

app = Flask(__name__)


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


BASE_CSS = """
<style>
  :root {
    color-scheme: light;
    --surface: #fcfcfb; --plane: #f9f9f7;
    --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
    --c-content: #2a78d6; --c-answer_key: #1baf7a; --c-cover: #eda100;
    --c-index: #4a3aa7; --c-blank: #898781; --critical: #d03b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --surface: #1a1a19; --plane: #0d0d0d;
      --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
      --c-content: #3987e5; --c-answer_key: #199e70; --c-cover: #c98500;
      --c-index: #9085e9; --c-blank: #898781;
    }
  }
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--plane); color: var(--ink);
         font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         padding: 24px; }
  a { color: inherit; }
  h1 { font-size: 20px; } h1 small { color: var(--muted); font-weight: 400; }
  .sub { color: var(--ink-2); margin: 4px 0 20px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin-bottom: 20px; }
  .tile { background: var(--surface); border: 1px solid var(--border);
          border-radius: 10px; padding: 14px 16px; }
  .tile .v { font-size: 26px; font-weight: 650; }
  .tile .l { color: var(--ink-2); font-size: 12px; }
  .panel { background: var(--surface); border: 1px solid var(--border);
           border-radius: 10px; padding: 16px; margin-bottom: 20px; }
  .panel h2 { font-size: 13px; color: var(--ink-2); font-weight: 600;
              text-transform: uppercase; letter-spacing: .04em; margin-bottom: 12px; }
  .srcrow { display: grid; grid-template-columns: 260px 1fr 60px; gap: 12px;
            align-items: center; padding: 6px 0; }
  .srcrow .name { font-size: 13px; color: var(--ink-2); overflow: hidden;
                  text-overflow: ellipsis; white-space: nowrap; }
  .srcrow .n { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { display: flex; gap: 2px; height: 14px; border-radius: 4px; overflow: hidden; }
  .bar div { min-width: 3px; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px;
            color: var(--ink-2); font-size: 12px; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
         margin-right: 5px; vertical-align: -1px; }
  form.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
  select, button { background: var(--surface); color: var(--ink);
          border: 1px solid var(--grid); border-radius: 8px; padding: 6px 10px;
          font: inherit; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
          gap: 12px; }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: 10px; overflow: hidden; text-decoration: none;
          display: block; }
  .card:hover { border-color: var(--muted); }
  .card img { width: 100%; aspect-ratio: 17/22; object-fit: contain;
              background: #fff; border-bottom: 1px solid var(--grid); display: block; }
  .card .meta { padding: 8px 10px; }
  .card .t { font-size: 12px; color: var(--ink-2); white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
  .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
  .badge { font-size: 11px; padding: 1px 8px; border-radius: 999px;
           border: 1px solid var(--grid); color: var(--ink-2); }
  .badge .dot { margin-right: 4px; }
  .restricted { color: var(--critical); border-color: var(--critical);
                font-weight: 600; }
  .pager { display: flex; gap: 10px; align-items: center; margin: 18px 0;
           color: var(--ink-2); }
  table.stats { border-collapse: collapse; width: 100%; }
  table.stats td { padding: 5px 10px; border-bottom: 1px solid var(--grid); }
  table.stats td:first-child { color: var(--ink-2); width: 180px; }
  pre.textlayer { background: var(--plane); border: 1px solid var(--grid);
                  border-radius: 8px; padding: 12px; white-space: pre-wrap;
                  max-height: 420px; overflow: auto; font-size: 12px; }
  .cols { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 4fr);
          gap: 20px; align-items: start; }
  @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
  .pageimg { width: 100%; border: 1px solid var(--grid); border-radius: 8px;
             background: #fff; }
  .banner { border: 1px solid var(--critical); color: var(--critical);
            border-radius: 8px; padding: 8px 12px; margin-bottom: 14px;
            font-weight: 600; }
</style>
"""

INDEX_TEMPLATE = BASE_CSS + """
<title>SAT QBank - Rendering & Routing Review</title>
<h1>Rendering &amp; Routing Review <small>Phase 3</small></h1>
<p class="sub">Every ledgered PDF page, rendered, measured, classified, and routed.</p>

<div class="tiles">
  <div class="tile"><div class="v">{{ totals.pages }}</div><div class="l">pages rendered</div></div>
  <div class="tile"><div class="v">{{ totals.content }}</div><div class="l">content pages</div></div>
  <div class="tile"><div class="v">{{ totals.answer_key }}</div><div class="l">answer-key pages</div></div>
  <div class="tile"><div class="v">{{ totals.text_pct }}%</div><div class="l">routed to text path</div></div>
  <div class="tile"><div class="v">{{ totals.image }}</div><div class="l">routed to image/OCR</div></div>
  {% if ocr_totals %}
  <div class="tile"><div class="v">{{ ocr_totals.n }}</div><div class="l">pages OCR-recovered (mean conf {{ ocr_totals.conf }})</div></div>
  {% endif %}
</div>

<div class="panel">
  <h2>Classification by source</h2>
  {% for s in per_source %}
  <div class="srcrow">
    <div class="name" title="{{ s.source_id }}">{{ s.source_id }}</div>
    <div class="bar">
      {% for cls in classes %}{% if s[cls] %}
      <div style="flex:{{ s[cls] }};background:var(--c-{{ cls }})"
           title="{{ cls }}: {{ s[cls] }} of {{ s.n }} pages"></div>
      {% endif %}{% endfor %}
    </div>
    <div class="n">{{ s.n }}</div>
  </div>
  {% endfor %}
  <div class="legend">
    {% for cls in classes %}
    <span><span class="dot" style="background:var(--c-{{ cls }})"></span>{{ cls }}</span>
    {% endfor %}
  </div>
</div>

<form class="filters" method="get">
  <select name="source">
    <option value="">all sources</option>
    {% for s in sources %}
    <option value="{{ s }}" {{ 'selected' if s == f_source }}>{{ s }}</option>
    {% endfor %}
  </select>
  <select name="cls">
    <option value="">all classifications</option>
    {% for c in classes %}
    <option value="{{ c }}" {{ 'selected' if c == f_cls }}>{{ c }}</option>
    {% endfor %}
  </select>
  <select name="route">
    <option value="">all routes</option>
    {% for r in routes %}
    <option value="{{ r }}" {{ 'selected' if r == f_route }}>{{ r }}</option>
    {% endfor %}
  </select>
  <button type="submit">Filter</button>
</form>

<div class="pager">
  <span>{{ matched }} pages match</span>
  {% if page > 1 %}<a href="{{ page_url(page - 1) }}">&laquo; prev</a>{% endif %}
  <span>page {{ page }} / {{ pages_total }}</span>
  {% if page < pages_total %}<a href="{{ page_url(page + 1) }}">next &raquo;</a>{% endif %}
</div>

<div class="grid">
  {% for r in rows %}
  <a class="card" href="/page/{{ r.source_id }}/{{ r.doc }}/{{ r.page_num }}"
     title="{{ r.reason }}">
    <img src="/asset/{{ r.thumb_path | strippages }}" loading="lazy" alt="page {{ r.page_num }}">
    <div class="meta">
      <div class="t">{{ r.doc }} &middot; p.{{ r.page_num }}</div>
      <div class="badges">
        <span class="badge"><span class="dot" style="background:var(--c-{{ r.classification }})"></span>{{ r.classification }}</span>
        <span class="badge">route: {{ r.route }}</span>
        {% if r.usage_tag and r.usage_tag.startswith('RESTRICTED') %}
        <span class="badge restricted">&#9888; restricted</span>
        {% endif %}
      </div>
    </div>
  </a>
  {% endfor %}
</div>
"""

DETAIL_TEMPLATE = BASE_CSS + """
<title>{{ r.doc }} p.{{ r.page_num }} - quality card</title>
<p class="sub"><a href="/">&laquo; back to review board</a></p>
<h1>{{ r.doc }} <small>page {{ r.page_num }} &middot; {{ r.source_id }}</small></h1>
<p class="sub">
  {% if prev %}<a href="/page/{{ r.source_id }}/{{ r.doc }}/{{ prev }}">&laquo; p.{{ prev }}</a>{% endif %}
  {% if next %} &nbsp;<a href="/page/{{ r.source_id }}/{{ r.doc }}/{{ next }}">p.{{ next }} &raquo;</a>{% endif %}
</p>
{% if r.usage_tag and r.usage_tag.startswith('RESTRICTED') %}
<div class="banner">&#9888; RESTRICTED source &mdash; internal review only, do not publish or screenshot for public documents.</div>
{% endif %}
<div class="cols">
  <div><img class="pageimg" src="/asset/{{ r.image_path | strippages }}" alt="full page render"></div>
  <div>
    <div class="panel">
      <h2>Quality card</h2>
      <table class="stats">
        <tr><td>classification</td><td><span class="dot" style="background:var(--c-{{ r.classification }})"></span><b>{{ r.classification }}</b></td></tr>
        <tr><td>route</td><td><b>{{ r.route }}</b></td></tr>
        <tr><td>decision reason</td><td>{{ r.reason }}</td></tr>
        <tr><td>text characters</td><td>{{ r.text_chars }}</td></tr>
        <tr><td>word count</td><td>{{ r.word_count }}</td></tr>
        <tr><td>alphanumeric ratio</td><td>{{ '%.3f' | format(r.alnum_ratio) }}</td></tr>
        <tr><td>ink density (center)</td><td>{{ '%.4f' | format(r.ink_ratio) }}</td></tr>
        <tr><td>orientation</td><td>{{ r.orientation }} ({{ '%.0f' | format(r.width_pt) }} &times; {{ '%.0f' | format(r.height_pt) }} pt)</td></tr>
        <tr><td>usage tag</td><td>{{ r.usage_tag }}</td></tr>
        <tr><td>rendered at</td><td>{{ r.rendered_at }}</td></tr>
      </table>
    </div>
    <div class="panel">
      <h2>Extracted text layer</h2>
      <pre class="textlayer">{{ text if text else '(no embedded text on this page)' }}</pre>
    </div>
    {% if ocr %}
    <div class="panel">
      <h2>OCR text ({{ ocr.engine }}, {{ ocr.dpi }} DPI)</h2>
      <p class="sub">mean confidence {{ ocr.mean_conf }} &middot; {{ ocr.word_count }} words &middot; quality: <b>{{ ocr.quality_flag }}</b></p>
      <pre class="textlayer">{{ ocr_text if ocr_text else '(OCR produced no text)' }}</pre>
    </div>
    {% endif %}
  </div>
</div>
"""


@app.template_filter("strippages")
def strippages(path: str) -> str:
    return path.removeprefix("data/pages/")


@app.get("/")
def index():
    f_source = request.args.get("source", "")
    f_cls = request.args.get("cls", "")
    f_route = request.args.get("route", "")
    page = max(1, request.args.get("p", 1, type=int))

    where, args = ["1=1"], []
    if f_source:
        where.append("source_id = ?"); args.append(f_source)
    if f_cls in CLASSES:
        where.append("classification = ?"); args.append(f_cls)
    if f_route in ROUTES:
        where.append("route = ?"); args.append(f_route)
    where_sql = " AND ".join(where)

    totals_row = query(
        """SELECT COUNT(*) AS pages,
                  SUM(classification='content') AS content,
                  SUM(classification='answer_key') AS answer_key,
                  SUM(route='image') AS image,
                  CAST(ROUND(100.0 * SUM(route='text') / COUNT(*)) AS INTEGER) AS text_pct
           FROM pages"""
    )[0]

    ocr_totals = None
    if query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ocr_results'"):
        row = query(
            "SELECT COUNT(*) AS n, ROUND(AVG(mean_conf), 1) AS conf FROM ocr_results"
        )[0]
        if row["n"]:
            ocr_totals = row

    per_source = query(
        f"""SELECT source_id, COUNT(*) AS n,
                   {', '.join(f"SUM(classification='{c}') AS \"{c}\"" for c in CLASSES)}
            FROM pages GROUP BY source_id ORDER BY source_id"""
    )

    matched = query(f"SELECT COUNT(*) AS n FROM pages WHERE {where_sql}", tuple(args))[0]["n"]
    pages_total = max(1, -(-matched // PER_PAGE))
    page = min(page, pages_total)
    rows = query(
        f"""SELECT * FROM pages WHERE {where_sql}
            ORDER BY source_id, doc, page_num LIMIT ? OFFSET ?""",
        tuple(args) + (PER_PAGE, (page - 1) * PER_PAGE),
    )

    def page_url(n: int) -> str:
        parts = [f"p={n}"]
        if f_source: parts.append(f"source={f_source}")
        if f_cls: parts.append(f"cls={f_cls}")
        if f_route: parts.append(f"route={f_route}")
        return "/?" + "&".join(parts)

    return render_template_string(
        INDEX_TEMPLATE, totals=totals_row, per_source=per_source,
        sources=[r["source_id"] for r in per_source], classes=CLASSES,
        routes=ROUTES, rows=rows, matched=matched, page=page,
        pages_total=pages_total, f_source=f_source, f_cls=f_cls,
        f_route=f_route, page_url=page_url, ocr_totals=ocr_totals,
    )


@app.get("/page/<source>/<doc>/<int:num>")
def page_detail(source: str, doc: str, num: int):
    rows = query(
        "SELECT * FROM pages WHERE source_id=? AND doc=? AND page_num=?",
        (source, doc, num),
    )
    if not rows:
        abort(404)
    row = rows[0]
    text_file = PROJECT_ROOT / row["text_path"]
    text = text_file.read_text(encoding="utf-8") if text_file.exists() else ""
    ocr_row, ocr_text = None, ""
    if query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ocr_results'"):
        found = query(
            "SELECT * FROM ocr_results WHERE source_id=? AND doc=? AND page_num=?",
            (source, doc, num),
        )
        if found:
            ocr_row = found[0]
            ocr_file = PROJECT_ROOT / ocr_row["ocr_path"]
            if ocr_file.exists():
                ocr_text = ocr_file.read_text(encoding="utf-8", errors="replace").strip()
    neighbors = {
        n for (n,) in query(
            "SELECT page_num FROM pages WHERE source_id=? AND doc=? AND page_num IN (?, ?)",
            (source, doc, num - 1, num + 1),
        )
    }
    return render_template_string(
        DETAIL_TEMPLATE, r=row, text=text.strip(),
        ocr=ocr_row, ocr_text=ocr_text,
        prev=num - 1 if num - 1 in neighbors else None,
        next=num + 1 if num + 1 in neighbors else None,
    )


@app.get("/asset/<path:relpath>")
def asset(relpath: str):
    return send_from_directory(PAGES_DIR, relpath)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
