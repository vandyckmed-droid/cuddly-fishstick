# report.py
# HTML report layer. Reads the cache via db.py, computes via shared.py,
# renders a self-contained HTML file, and opens it in WebView.
# No FMP fetching. No model changes. Pure presentation.

import os
import json
import webbrowser
from datetime import datetime

import numpy as np

import db
import shared

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(ROOT, "reports")
LATEST_PATH = os.path.join(REPORTS_DIR, "latest.html")

os.makedirs(REPORTS_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Inline CSS
# --------------------------------------------------------------------------- #
CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                 "Helvetica Neue", Arial, sans-serif;
    background: #0e1014;
    color: #e6e8ec;
    margin: 0;
    padding: 16px;
    font-size: 14px;
    line-height: 1.4;
}
h1, h2 { font-weight: 600; margin: 24px 0 12px 0; }
h1 { font-size: 22px; color: #ffffff; }
h2 { font-size: 17px; color: #bfc4cc; border-bottom: 1px solid #23272f;
     padding-bottom: 6px; }
.muted { color: #8b919b; font-size: 12px; }

.stats {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin: 12px 0 24px 0;
}
.stat {
    background: #161a21;
    border: 1px solid #23272f;
    border-radius: 8px;
    padding: 10px 12px;
}
.stat .label { font-size: 11px; color: #8b919b; text-transform: uppercase;
               letter-spacing: 0.5px; }
.stat .value { font-size: 16px; font-weight: 600; color: #ffffff;
               margin-top: 2px; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0 16px 0;
    background: #161a21;
    border: 1px solid #23272f;
    border-radius: 8px;
    overflow: hidden;
}
th, td {
    padding: 8px 10px;
    text-align: right;
    border-bottom: 1px solid #23272f;
    font-variant-numeric: tabular-nums;
}
th:first-child, td:first-child { text-align: left; }
th {
    background: #1a1e26;
    color: #bfc4cc;
    font-weight: 600;
    font-size: 12px;
    cursor: pointer;
    user-select: none;
    position: sticky;
    top: 0;
}
th:hover { background: #232831; color: #ffffff; }
th.sorted-asc::after { content: " ▲"; font-size: 10px; color: #6b8aff; }
th.sorted-desc::after { content: " ▼"; font-size: 10px; color: #6b8aff; }
tbody tr.row-main { cursor: pointer; }
tbody tr.row-main:hover { background: #1a1e26; }
tbody tr.row-detail { display: none; background: #11141a; }
tbody tr.row-detail.open { display: table-row; }
tbody tr.row-detail td {
    padding: 12px 16px;
    text-align: left;
    border-bottom: 1px solid #23272f;
}
tbody tr:last-child td { border-bottom: none; }
.detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 6px 16px;
}
.detail-grid .group-header {
    grid-column: 1 / -1;
    color: #8b919b;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 6px;
}
.detail-grid .pair {
    display: flex;
    justify-content: space-between;
    border-bottom: 1px dashed #23272f;
    padding: 2px 0;
}
.detail-grid .pair span:first-child { color: #8b919b; }
.detail-grid .pair span:last-child {
    font-variant-numeric: tabular-nums;
    font-weight: 500;
}

.pos { color: #4ade80; }
.neg { color: #f87171; }
.zero { color: #8b919b; }

.sector-bar {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 8px 0;
}
.sector-row {
    display: grid;
    grid-template-columns: 140px 1fr 60px;
    align-items: center;
    gap: 8px;
    font-size: 13px;
}
.sector-row .name { color: #bfc4cc; }
.sector-row .bar {
    height: 14px;
    background: #1a1e26;
    border-radius: 3px;
    overflow: hidden;
    position: relative;
}
.sector-row .bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #6b8aff, #4ade80);
    border-radius: 3px;
}
.sector-row .pct {
    text-align: right;
    font-variant-numeric: tabular-nums;
}

.book-rank {
    color: #8b919b;
    font-size: 11px;
}
.expand-hint { color: #6b8aff; font-size: 11px; margin-left: 4px; }

.footer {
    margin-top: 24px;
    color: #8b919b;
    font-size: 11px;
    text-align: center;
    border-top: 1px solid #23272f;
    padding-top: 12px;
}
"""

# --------------------------------------------------------------------------- #
# Inline JavaScript — table sorting + row expansion
# --------------------------------------------------------------------------- #
JS = """
document.addEventListener('DOMContentLoaded', function() {
    // Sortable tables
    document.querySelectorAll('table.sortable').forEach(function(table) {
        const ths = table.querySelectorAll('thead th');
        ths.forEach(function(th, colIdx) {
            th.addEventListener('click', function() {
                const tbody = table.querySelector('tbody');
                const allRows = Array.from(tbody.querySelectorAll('tr'));
                // Pair main rows with their detail rows
                const pairs = [];
                for (let i = 0; i < allRows.length; i++) {
                    const r = allRows[i];
                    if (r.classList.contains('row-main')) {
                        const d = (i+1 < allRows.length &&
                                   allRows[i+1].classList.contains('row-detail'))
                                   ? allRows[i+1] : null;
                        pairs.push([r, d]);
                    }
                }
                // Determine sort direction
                const wasAsc = th.classList.contains('sorted-asc');
                ths.forEach(function(other) {
                    other.classList.remove('sorted-asc', 'sorted-desc');
                });
                th.classList.add(wasAsc ? 'sorted-desc' : 'sorted-asc');
                const dir = wasAsc ? -1 : 1;

                pairs.sort(function(a, b) {
                    const ca = a[0].cells[colIdx];
                    const cb = b[0].cells[colIdx];
                    const va = ca.dataset.sort !== undefined
                        ? parseFloat(ca.dataset.sort)
                        : ca.textContent.trim();
                    const vb = cb.dataset.sort !== undefined
                        ? parseFloat(cb.dataset.sort)
                        : cb.textContent.trim();
                    const na = parseFloat(va);
                    const nb = parseFloat(vb);
                    if (!isNaN(na) && !isNaN(nb)) {
                        return (na - nb) * dir;
                    }
                    return String(va).localeCompare(String(vb)) * dir;
                });

                pairs.forEach(function(p) {
                    tbody.appendChild(p[0]);
                    if (p[1]) tbody.appendChild(p[1]);
                });
            });
        });
    });

    // Expandable rows
    document.querySelectorAll('tr.row-main').forEach(function(row) {
        row.addEventListener('click', function() {
            const next = row.nextElementSibling;
            if (next && next.classList.contains('row-detail')) {
                next.classList.toggle('open');
            }
        });
    });
});
"""


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def fmt_z(x, dp=2):
    if x is None or not np.isfinite(x):
        return ('<span class="zero">—</span>', "")
    sign = "+" if x > 0 else ""
    cls = "pos" if x > 0 else ("neg" if x < 0 else "zero")
    return (f'<span class="{cls}">{sign}{x:.{dp}f}</span>', f"{x:.6f}")


def fmt_pct(x, dp=1):
    if x is None or not np.isfinite(x):
        return ('<span class="zero">—</span>', "")
    cls = "pos" if x > 0 else ("neg" if x < 0 else "zero")
    return (f'<span class="{cls}">{x*100:.{dp}f}%</span>', f"{x:.6f}")


def fmt_pct_plain(x, dp=1):
    if x is None or not np.isfinite(x):
        return ('—', "")
    return (f"{x*100:.{dp}f}%", f"{x:.6f}")


def fmt_int(x):
    if x is None or not np.isfinite(x):
        return ('—', "")
    return (f"{int(x)}", f"{int(x)}")


def fmt_text(s):
    return (str(s), str(s))


# --------------------------------------------------------------------------- #
# Section renderers
# --------------------------------------------------------------------------- #
def render_header(meta):
    return f"""
<h1>Factor Book</h1>
<div class="muted">Generated {meta['now']} · {meta['n_universe']} tickers · cache {meta['cache_age']}</div>
<div class="stats">
  <div class="stat">
    <div class="label">Universe</div>
    <div class="value">{meta['n_universe']}</div>
  </div>
  <div class="stat">
    <div class="label">Sectors</div>
    <div class="value">{meta['n_sectors']}</div>
  </div>
  <div class="stat">
    <div class="label">Top of book</div>
    <div class="value">{meta['top_ticker']} <span class="muted">({meta['top_comp']})</span></div>
  </div>
  <div class="stat">
    <div class="label">Portfolio σ (annual)</div>
    <div class="value">{meta['portfolio_vol']}</div>
  </div>
</div>
"""


def render_factor_table(tickers, data):
    """Sortable table with one main row per ticker and a hidden detail row."""
    rows_html = []
    for i, t in enumerate(tickers):
        v_html, v_sort = fmt_z(data["value"][i])
        q_html, q_sort = fmt_z(data["quality"][i])
        m_html, m_sort = fmt_z(data["momentum"][i])
        c_html, c_sort = fmt_z(data["composite"][i])
        rk = data["rank"][i]
        rk_html = f"{int(rk)}" if np.isfinite(rk) else "—"
        rk_sort = f"{int(rk)}" if np.isfinite(rk) else "9999"
        sector = data["sectors"][i] or "Unknown"

        rows_html.append(f"""
<tr class="row-main">
  <td>{t} <span class="expand-hint">▾</span></td>
  <td>{sector}</td>
  <td data-sort="{v_sort}">{v_html}</td>
  <td data-sort="{q_sort}">{q_html}</td>
  <td data-sort="{m_sort}">{m_html}</td>
  <td data-sort="{c_sort}">{c_html}</td>
  <td data-sort="{rk_sort}">{rk_html}</td>
</tr>
<tr class="row-detail">
  <td colspan="7">
    {render_detail_grid(i, data)}
  </td>
</tr>
""")

    return f"""
<h2>Factor Table</h2>
<div class="muted">Tap a row for sub-component breakdown · tap a column header to sort</div>
<table class="sortable">
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Sector</th>
      <th>Value</th>
      <th>Quality</th>
      <th>Momentum</th>
      <th>Composite</th>
      <th>Rank</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows_html)}
  </tbody>
</table>
"""


def render_detail_grid(i, data):
    """Sub-component z-scores for one ticker."""
    subs = data["subs"]
    parts = []

    parts.append('<div class="detail-grid">')
    parts.append('<div class="group-header">VALUE</div>')
    for label, key in [("EBIT/EV", "z_ebit_ev"), ("FCF/EV", "z_fcf_ev"),
                       ("B/M", "z_bm"), ("Sales/EV", "z_sales_ev")]:
        v_html, _ = fmt_z(subs[key][i])
        parts.append(f'<div class="pair"><span>{label}</span><span>{v_html}</span></div>')

    parts.append('<div class="group-header">QUALITY</div>')
    for label, key in [("GP/Assets", "z_gp_ta"), ("Op Margin", "z_op_margin"),
                       ("−NetDebt/Assets", "z_low_lev")]:
        v_html, _ = fmt_z(subs[key][i])
        parts.append(f'<div class="pair"><span>{label}</span><span>{v_html}</span></div>')

    parts.append('<div class="group-header">MOMENTUM</div>')
    for label, key in [("z_m_long (12m-1m)", "z_m_long"),
                       ("z_m_short (6m)", "z_m_short")]:
        v_html, _ = fmt_z(subs[key][i])
        parts.append(f'<div class="pair"><span>{label}</span><span>{v_html}</span></div>')

    # Raw m-stats too
    ml_html, _ = fmt_z(subs["m_long_raw"][i])
    ms_html, _ = fmt_z(subs["m_short_raw"][i])
    parts.append(f'<div class="pair"><span>m_long (raw)</span><span>{ml_html}</span></div>')
    parts.append(f'<div class="pair"><span>m_short (raw)</span><span>{ms_html}</span></div>')

    parts.append('</div>')
    return ''.join(parts)


def render_book_section(book, sectors_map):
    """Top-N book with weights, vols, sectors."""
    if book is None:
        return '<h2>Book</h2><div class="muted">No book produced.</div>'

    kept = book["kept"]
    w_rel = book["w_rel"]
    sigma_ann = book["sigma_ann"]
    sigma_p = book["sigma_p"]
    scale = book["scale"]
    cap_info = book["cap_info"]

    # Sort by w_rel desc
    order = sorted(range(len(kept)), key=lambda j: -w_rel[j])

    rows_html = []
    for rank_i, j in enumerate(order, 1):
        t = kept[j]
        sec = sectors_map.get(t, "Unknown")
        wr_html, wr_sort = fmt_pct(w_rel[j], dp=1)
        sa_html, sa_sort = fmt_pct(sigma_ann[j], dp=1)
        rows_html.append(f"""
<tr class="row-main">
  <td><span class="book-rank">#{rank_i}</span> {t}</td>
  <td>{sec}</td>
  <td data-sort="{wr_sort}">{wr_html}</td>
  <td data-sort="{sa_sort}">{sa_html}</td>
</tr>
""")

    # No detail rows here — book table is simpler
    cap_summary = ""
    if cap_info["capped_sectors"]:
        cap_summary = (
            f'<div class="muted">Sector cap engaged on '
            f'{", ".join(set(cap_info["capped_sectors"]))} '
            f'({cap_info["iters"]} iter)</div>'
        )

    sigma_p_pct = f"{sigma_p*100:.1f}%" if np.isfinite(sigma_p) else "—"
    scale_str = f"{scale:.2f}×" if np.isfinite(scale) else "—"

    return f"""
<h2>Book ({len(kept)} names)</h2>
<div class="muted">
  Pre-vol-scale relative weights · portfolio σ = {sigma_p_pct} ·
  vol-scale = {scale_str}
</div>
{cap_summary}
<table class="sortable">
  <thead>
    <tr>
      <th>Ticker</th>
      <th>Sector</th>
      <th>w_rel</th>
      <th>σ ann</th>
    </tr>
  </thead>
  <tbody>
    {''.join(rows_html)}
  </tbody>
</table>
"""


def render_sector_breakdown(tickers, data, book, sectors_map):
    """Two views: sector counts in universe + sector weights in book."""
    # Universe sector sizes from data
    sector_sizes = data.get("sector_sizes", {})
    total = sum(sector_sizes.values()) if sector_sizes else 0

    universe_rows = []
    for sec, n in sorted(sector_sizes.items(), key=lambda kv: -kv[1]):
        pct = n / total if total > 0 else 0.0
        universe_rows.append(f"""
<div class="sector-row">
  <div class="name">{sec}</div>
  <div class="bar"><div class="bar-fill" style="width: {pct*100:.1f}%"></div></div>
  <div class="pct">{n} ({pct*100:.0f}%)</div>
</div>
""")

    # Book sector weights
    book_rows = []
    if book is not None:
        kept = book["kept"]
        w_rel = book["w_rel"]
        sec_w = {}
        for j, t in enumerate(kept):
            sec = sectors_map.get(t, "Unknown")
            sec_w[sec] = sec_w.get(sec, 0.0) + float(w_rel[j])
        for sec, w in sorted(sec_w.items(), key=lambda kv: -kv[1]):
            book_rows.append(f"""
<div class="sector-row">
  <div class="name">{sec}</div>
  <div class="bar"><div class="bar-fill" style="width: {w*100:.1f}%"></div></div>
  <div class="pct">{w*100:.1f}%</div>
</div>
""")
    else:
        book_rows.append('<div class="muted">No book.</div>')

    return f"""
<h2>Sector Breakdown</h2>
<div class="muted">Universe composition</div>
<div class="sector-bar">{''.join(universe_rows)}</div>
<div class="muted" style="margin-top: 16px">Book weights by sector</div>
<div class="sector-bar">{''.join(book_rows)}</div>
"""


# --------------------------------------------------------------------------- #
# Main composer
# --------------------------------------------------------------------------- #
def build_html(tickers, data, book, sectors_map, meta):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Factor Book — {meta['now']}</title>
<style>{CSS}</style>
</head>
<body>

{render_header(meta)}

{render_factor_table(tickers, data)}

{render_book_section(book, sectors_map)}

{render_sector_breakdown(tickers, data, book, sectors_map)}

<div class="footer">
  cuddly-fishstick · {meta['n_universe']} ticker universe ·
  generated by report.py
</div>

<script>{JS}</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Cache age helper
# --------------------------------------------------------------------------- #
def _cache_age_str(conn):
    p_upd = db.meta_get(conn, "prices_updated")
    if not p_upd:
        return "unknown"
    try:
        d = datetime.fromisoformat(p_upd)
        delta = datetime.utcnow() - d
        if delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        if delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        return f"{delta.days}d ago"
    except Exception:
        return p_upd


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
def generate_report(open_in_browser=True, verbose=True):
    """Generate the HTML report. Returns path to latest.html."""
    if verbose:
        print("=" * 56)
        print("  report.py — generating factor book")
        print("=" * 56)

    if not db.cache_exists():
        raise FileNotFoundError(
            "cache.db does not exist. Run cache.py first."
        )

    conn = db.open_cache(read_only=True)
    try:
        # Load
        universe = db.load_universe(conn, include_market=False)
        fin_records = db.load_all_financials(conn)
        fins = {t: db.extract_fields(fin_records.get(t)) for t in universe
                if fin_records.get(t)}
        price_with_dates = db.load_prices_bulk_with_dates(
            conn, universe + [db.MARKET_TICKER]
        )
        mkt_dates, mkt_close = db.load_market(conn)
        sectors_map = db.load_universe_with_sectors(conn)

        if verbose:
            print(f"  Loaded {len(universe)} tickers from cache")

        # Compute factors
        tix, data = shared.compute_factors(
            fins, price_with_dates, mkt_dates, mkt_close
        )

        # Build book
        book = shared.build_book(price_with_dates, tix, data, sectors_map,
                                  n=shared.TOP_N)

        # Top-of-book stat
        comp = data["composite"]
        finite_idx = [i for i in range(len(tix)) if np.isfinite(comp[i])]
        if finite_idx:
            top_i = max(finite_idx, key=lambda i: comp[i])
            top_ticker = tix[top_i]
            top_comp = f"{comp[top_i]:+.2f}"
        else:
            top_ticker = "—"
            top_comp = "—"

        portfolio_vol = "—"
        if book is not None and np.isfinite(book.get("sigma_p", float("nan"))):
            portfolio_vol = f"{book['sigma_p']*100:.1f}%"

        meta = {
            "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "n_universe": len(tix),
            "n_sectors": len(data.get("sector_sizes", {})),
            "top_ticker": top_ticker,
            "top_comp": top_comp,
            "portfolio_vol": portfolio_vol,
            "cache_age": _cache_age_str(conn),
        }

        # Render
        html = build_html(tix, data, book, sectors_map, meta)

        # Write timestamped + latest
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ts_path = os.path.join(REPORTS_DIR, f"report_{ts}.html")
        with open(ts_path, "w", encoding="utf-8") as f:
            f.write(html)
        with open(LATEST_PATH, "w", encoding="utf-8") as f:
            f.write(html)

        if verbose:
            print(f"  Wrote {ts_path}")
            print(f"  Wrote {LATEST_PATH}")

    finally:
        conn.close()

    if open_in_browser:
        if verbose:
            print(f"  Opening in WebView...")
        webbrowser.open(f"file://{LATEST_PATH}")

    return LATEST_PATH


# --------------------------------------------------------------------------- #
# Self-tests
# --------------------------------------------------------------------------- #
def run_self_tests():
    print("=" * 56)
    print("  report.py self-tests")
    print("=" * 56)

    failures = 0

    if not db.cache_exists():
        print("  FAIL: cache.db does not exist. Run cache.py first.")
        return False

    try:
        path = generate_report(open_in_browser=False, verbose=False)
        print(f"  ✓ generate_report() returned: {os.path.basename(path)}")
    except Exception as e:
        failures += 1
        print(f"  ✗ generate_report raised: {e}")
        return False

    # File exists
    if os.path.exists(LATEST_PATH):
        print(f"  ✓ latest.html exists")
    else:
        failures += 1
        print(f"  ✗ latest.html missing")

    # File non-empty
    size = os.path.getsize(LATEST_PATH) if os.path.exists(LATEST_PATH) else 0
    if size > 1000:
        print(f"  ✓ latest.html is {size} bytes")
    else:
        failures += 1
        print(f"  ✗ latest.html too small: {size} bytes")

    # Expected tickers appear in HTML
    with open(LATEST_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    conn = db.open_cache(read_only=True)
    universe = db.load_universe(conn, include_market=False)
    conn.close()

    missing = [t for t in universe if t not in html]
    if not missing:
        print(f"  ✓ all {len(universe)} tickers appear in HTML")
    else:
        failures += 1
        print(f"  ✗ tickers missing from HTML: {missing}")

    # Timestamped file also written
    timestamped = [f for f in os.listdir(REPORTS_DIR)
                   if f.startswith("report_") and f.endswith(".html")]
    if timestamped:
        print(f"  ✓ {len(timestamped)} timestamped report(s) in reports/")
    else:
        failures += 1
        print(f"  ✗ no timestamped reports found")

    print("=" * 56)
    if failures == 0:
        print(f"  ALL TESTS PASSED")
    else:
        print(f"  {failures} TEST(S) FAILED")
    print("=" * 56)
    return failures == 0


if __name__ == "__main__":
    # Self-tests, then open the report
    ok = run_self_tests()
    if ok:
        print("\nOpening latest report in WebView...")
        webbrowser.open(f"file://{LATEST_PATH}")
