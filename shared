# cache.py
# Cache maintainer for the factor system.
# Read & write SQLite. No factor math. No reporting. Single concern.
#
# Phase 1: 8-name test universe + SPY.
# Modes: full / prices / financials / status.

import os
import json
import time
import gzip
import shutil
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from mysecrets import API_KEY

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "cache.db")
BACKUP_PATH = os.path.join(DATA_DIR, "cache.db.bak")

BASE = "https://financialmodelingprep.com/stable"
REQUEST_SLEEP = 0.1
TIMEOUT = 30

# Refresh thresholds
UNIVERSE_REFRESH_DAYS = 7
FINANCIALS_REFRESH_DAYS = 21
PRICES_STALE_DAYS = 1

# History depth
PRICE_LOOKBACK_DAYS = 1100

# Phase 1 hardcoded test universe.
# (ticker, sector_hint) — sector_hint is provisional, profile fetch overrides.
UNIVERSE = [
    ("AAPL",  "Technology"),
    ("MSFT",  "Technology"),
    ("NVDA",  "Technology"),
    ("LULU",  "Consumer Cyclical"),
    ("JPM",   "Financial Services"),
    ("XOM",   "Energy"),
    ("BRK.B", "Financial Services"),
    ("KO",    "Consumer Defensive"),
]
MARKET_TICKER = "SPY"

os.makedirs(DATA_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# DB
# --------------------------------------------------------------------------- #
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS universe("
        "ticker TEXT PRIMARY KEY, sector TEXT, added_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS prices("
        "ticker TEXT, date TEXT, close REAL, "
        "PRIMARY KEY(ticker, date))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS financials("
        "ticker TEXT PRIMARY KEY, data TEXT, fetched_at TEXT)"
    )
    conn.commit()
    return conn


def meta_get(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def meta_set(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value)
    )
    conn.commit()


def backup_db():
    """Copy cache.db -> cache.db.bak before any write run."""
    if os.path.exists(DB_PATH):
        try:
            shutil.copy2(DB_PATH, BACKUP_PATH)
            print(f"  Backup written: {os.path.basename(BACKUP_PATH)}")
        except Exception as e:
            print(f"  Warning: backup failed: {e}")


# --------------------------------------------------------------------------- #
# FMP API (stdlib HTTP)
# --------------------------------------------------------------------------- #
def fmp_symbol(ticker):
    """Translate ticker to FMP's expected symbol form.
    BRK.B -> BRK-B, etc. Most US tickers pass through unchanged.
    """
    return ticker.replace(".", "-")


def api_get(path, params=None):
    p = dict(params or {})
    p["apikey"] = API_KEY
    url = f"{BASE}/{path}?{urlencode(p)}"
    req = Request(
        url,
        headers={"Accept-Encoding": "gzip", "User-Agent": "book-cache/1.0"},
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            time.sleep(REQUEST_SLEEP)
            return json.loads(raw.decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    except Exception:
        return None


def _first(rec):
    if isinstance(rec, list):
        return rec[0] if rec else None
    if isinstance(rec, dict):
        return rec
    return None


# --------------------------------------------------------------------------- #
# Universe
# --------------------------------------------------------------------------- #
def update_universe(conn):
    """For Phase 1: write the hardcoded list into the universe table."""
    now = datetime.utcnow().isoformat()
    print(f"Universe: writing {len(UNIVERSE)} hardcoded tickers")
    conn.execute("DELETE FROM universe")
    conn.executemany(
        "INSERT OR REPLACE INTO universe(ticker, sector, added_at) "
        "VALUES(?,?,?)",
        [(t, s, now) for (t, s) in UNIVERSE],
    )
    meta_set(conn, "universe_updated", now)
    conn.commit()


def list_universe(conn, include_market=True):
    rows = conn.execute(
        "SELECT ticker FROM universe ORDER BY ticker"
    ).fetchall()
    tickers = [r[0] for r in rows]
    if include_market and MARKET_TICKER not in tickers:
        tickers = tickers + [MARKET_TICKER]
    return tickers


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def _existing_price_range(conn, ticker):
    row = conn.execute(
        "SELECT MIN(date), MAX(date), COUNT(*) FROM prices WHERE ticker=?",
        (ticker,),
    ).fetchone()
    if not row or row[2] == 0:
        return None, None, 0
    return row[0], row[1], int(row[2])


def _fetch_price_range(ticker, start_iso, end_iso):
    """Fetch closes for ticker in [start, end]. Returns list of (date, close)."""
    fmp_t = fmp_symbol(ticker)
    data = api_get(
        "historical-price-eod/light",
        {"symbol": fmp_t, "from": start_iso, "to": end_iso},
    )
    if not data:
        return []
    records = data if isinstance(data, list) else data.get("historical", [])
    out = []
    for h in records:
        d = h.get("date")
        c = h.get("price")
        if c is None:
            c = h.get("adjClose")
        if c is None:
            c = h.get("close")
        if d and c is not None:
            try:
                out.append((d, float(c)))
            except (TypeError, ValueError):
                pass
    return out


def update_prices(conn):
    """Bring every ticker's price history up to date AND back to lookback."""
    today = datetime.utcnow().date()
    target_start = (today - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()
    target_end = today.isoformat()

    tickers = list_universe(conn, include_market=True)
    print(f"Prices: target range {target_start} to {target_end}")
    print(f"        {len(tickers)} tickers to check")

    fetched_total = 0
    skipped = 0

    for i, t in enumerate(tickers, 1):
        oldest, newest, count = _existing_price_range(conn, t)
        ranges_to_fetch = []

        if count == 0:
            ranges_to_fetch.append((target_start, target_end))
        else:
            if oldest > target_start:
                end_back = (
                    datetime.fromisoformat(oldest).date() - timedelta(days=1)
                ).isoformat()
                ranges_to_fetch.append((target_start, end_back))
            try:
                newest_d = datetime.fromisoformat(newest).date()
            except Exception:
                newest_d = None
            if newest_d and newest_d < today - timedelta(days=PRICES_STALE_DAYS):
                start_fwd = (newest_d + timedelta(days=1)).isoformat()
                ranges_to_fetch.append((start_fwd, target_end))

        if not ranges_to_fetch:
            skipped += 1
            print(f"  [{i}/{len(tickers)}] {t}: up-to-date "
                  f"({count} bars, {oldest} to {newest})")
            continue

        new_rows = []
        for s, e in ranges_to_fetch:
            print(f"  [{i}/{len(tickers)}] {t}: fetch {s} → {e}")
            rows = _fetch_price_range(t, s, e)
            new_rows.extend((t, d, c) for (d, c) in rows)

        if new_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO prices(ticker, date, close) "
                "VALUES(?,?,?)",
                new_rows,
            )
            conn.commit()
            fetched_total += len(new_rows)
            print(f"      {len(new_rows)} bars stored")
        else:
            print(f"      no data returned")

    meta_set(conn, "prices_updated", datetime.utcnow().isoformat())
    print(f"Prices: {fetched_total} new bars, {skipped} tickers skipped")


# --------------------------------------------------------------------------- #
# Financials
# --------------------------------------------------------------------------- #
def _financials_age_days(conn, ticker):
    row = conn.execute(
        "SELECT fetched_at FROM financials WHERE ticker=?", (ticker,)
    ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row[0])
        return (datetime.utcnow() - fetched).days
    except Exception:
        return None


def update_financials(conn):
    """Refresh quarterly fundamentals for any ticker whose record is older
    than FINANCIALS_REFRESH_DAYS."""
    tickers = list_universe(conn, include_market=False)
    print(f"Financials: checking {len(tickers)} tickers")

    fetched = skipped = 0

    for i, t in enumerate(tickers, 1):
        age = _financials_age_days(conn, t)
        if age is not None and age <= FINANCIALS_REFRESH_DAYS:
            skipped += 1
            print(f"  [{i}/{len(tickers)}] {t}: fresh ({age}d)")
            continue

        fmp_t = fmp_symbol(t)
        print(f"  [{i}/{len(tickers)}] {t}: fetch (FMP symbol: {fmp_t})")

        inc = api_get("income-statement",
                      {"symbol": fmp_t, "period": "quarter", "limit": 1})
        bal = api_get("balance-sheet-statement",
                      {"symbol": fmp_t, "period": "quarter", "limit": 1})
        cfs = api_get("cash-flow-statement",
                      {"symbol": fmp_t, "period": "quarter", "limit": 1})
        ev = api_get("enterprise-values",
                     {"symbol": fmp_t, "period": "quarter", "limit": 1})
        prof = api_get("profile", {"symbol": fmp_t})

        record = {
            "income": _first(inc),
            "balance": _first(bal),
            "cashflow": _first(cfs),
            "enterprise": _first(ev),
            "profile": _first(prof),
        }

        if all(record[k] is None for k in record):
            print(f"      no data returned, skipping")
            continue

        conn.execute(
            "INSERT OR REPLACE INTO financials(ticker, data, fetched_at) "
            "VALUES(?,?,?)",
            (t, json.dumps(record), datetime.utcnow().isoformat()),
        )
        prof_sec = (record.get("profile") or {}).get("sector")
        if prof_sec:
            conn.execute(
                "UPDATE universe SET sector=? WHERE ticker=?",
                (prof_sec, t),
            )
        conn.commit()
        fetched += 1

    meta_set(conn, "financials_updated", datetime.utcnow().isoformat())
    print(f"Financials: fetched={fetched} skipped={skipped}")


# --------------------------------------------------------------------------- #
# Status report
# --------------------------------------------------------------------------- #
def print_status(conn):
    """Read-only report on cache state. iPhone-readable."""
    print("\n" + "=" * 56)
    print("  CACHE STATUS")
    print("=" * 56)

    if os.path.exists(DB_PATH):
        size_kb = os.path.getsize(DB_PATH) / 1024.0
        print(f"  DB file:        {DB_PATH}")
        print(f"  Size:           {size_kb:.1f} KB")
    else:
        print(f"  DB file:        does not exist yet")
        return

    print(f"  Universe upd:   {meta_get(conn, 'universe_updated') or '—'}")
    print(f"  Prices upd:     {meta_get(conn, 'prices_updated') or '—'}")
    print(f"  Financials upd: {meta_get(conn, 'financials_updated') or '—'}")

    today = datetime.utcnow().date()
    target_start = (today - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()

    rows = conn.execute(
        "SELECT ticker, sector FROM universe ORDER BY ticker"
    ).fetchall()
    universe_tix = [r[0] for r in rows]

    print(f"\n  Universe ({len(universe_tix)}):")
    print(f"    {'Ticker':<8}{'Sector':<22}{'Bars':>6}{'Oldest':>13}"
          f"{'Newest':>13}  {'Fin':>7}")
    print("    " + "-" * 70)

    all_tickers = universe_tix + ([MARKET_TICKER] if MARKET_TICKER not in
                                   universe_tix else [])
    for t in all_tickers:
        if t == MARKET_TICKER:
            sec = "(market)"
        else:
            sec_row = conn.execute(
                "SELECT sector FROM universe WHERE ticker=?", (t,)
            ).fetchone()
            sec = (sec_row[0] if sec_row and sec_row[0] else "—")[:20]

        oldest, newest, count = _existing_price_range(conn, t)
        if count == 0:
            bars_str = "0"
            oldest_str = "—"
            newest_str = "—"
        else:
            bars_str = str(count)
            oldest_str = oldest or "—"
            newest_str = newest or "—"
            try:
                newest_d = datetime.fromisoformat(newest).date()
                if (today - newest_d).days > 5:
                    newest_str += "!"
            except Exception:
                pass
            if oldest and oldest > target_start:
                oldest_str += "!"

        age = _financials_age_days(conn, t)
        if t == MARKET_TICKER:
            fin_str = "n/a"
        elif age is None:
            fin_str = "—"
        else:
            fin_str = f"{age}d"
            if age > FINANCIALS_REFRESH_DAYS:
                fin_str += "!"

        print(f"    {t:<8}{sec:<22}{bars_str:>6}"
              f"{oldest_str:>13}{newest_str:>13}  {fin_str:>7}")

    print(f"\n  Target lookback: {target_start} ({PRICE_LOOKBACK_DAYS}d)")
    print(f"  '!' = stale or insufficient")
    print("=" * 56)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    print("=" * 56)
    print("  cache.py — cache maintainer")
    print("=" * 56)
    print("  [1] Full   (universe + prices + financials)")
    print("  [2] Prices only")
    print("  [3] Financials only")
    print("  [4] Status (no fetching)")
    print("  [enter] = full")
    print("=" * 56)

    try:
        choice = input("Mode: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    conn = get_conn()
    try:
        if choice in ("", "1", "full"):
            backup_db()
            update_universe(conn)
            update_prices(conn)
            update_financials(conn)
            print()
            print_status(conn)
        elif choice in ("2", "prices"):
            backup_db()
            if not list_universe(conn, include_market=False):
                update_universe(conn)
            update_prices(conn)
            print()
            print_status(conn)
        elif choice in ("3", "financials", "fundamentals"):
            backup_db()
            if not list_universe(conn, include_market=False):
                update_universe(conn)
            update_financials(conn)
            print()
            print_status(conn)
        elif choice in ("4", "status"):
            print_status(conn)
        else:
            print(f"Unknown mode: '{choice}'")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
