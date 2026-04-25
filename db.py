# db.py
# Read-only loaders into the cache. Schema lives here.
# All other scripts (shared.py, report.py, future viewers) import from this.
# Run directly to execute self-tests.

import os
import json
import sqlite3
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "cache.db")

# Schema constants
T_META = "meta"
T_UNIVERSE = "universe"
T_PRICES = "prices"
T_FINANCIALS = "financials"

MARKET_TICKER = "SPY"


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #
def open_cache(read_only=True):
    """Open the cache. Default is read-only — viewer scripts should not write.

    Pass read_only=False only when you're certain you need write access
    (which inside this project should only be cache.py).
    """
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Cache not found at {DB_PATH}. Run cache.py first."
        )
    if read_only:
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    return conn


def cache_exists():
    return os.path.exists(DB_PATH)


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
def meta_get(conn, key):
    row = conn.execute(
        f"SELECT value FROM {T_META} WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# Universe
# --------------------------------------------------------------------------- #
def load_universe(conn, include_market=False):
    """Return list of tickers in universe. Optionally append market ticker."""
    rows = conn.execute(
        f"SELECT ticker FROM {T_UNIVERSE} ORDER BY ticker"
    ).fetchall()
    tickers = [r[0] for r in rows]
    if include_market and MARKET_TICKER not in tickers:
        tickers = tickers + [MARKET_TICKER]
    return tickers


def load_universe_with_sectors(conn):
    """Return {ticker: sector} for the universe."""
    rows = conn.execute(
        f"SELECT ticker, sector FROM {T_UNIVERSE}"
    ).fetchall()
    return {r[0]: (r[1] or "Unknown") for r in rows}


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def _chunked(seq, n=400):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def load_prices(conn, ticker):
    """Closes for a single ticker as a numpy array, oldest first.
    Returns empty array if ticker not in cache."""
    rows = conn.execute(
        f"SELECT close FROM {T_PRICES} WHERE ticker=? ORDER BY date",
        (ticker,),
    ).fetchall()
    if not rows:
        return np.zeros(0, dtype=float)
    return np.asarray([r[0] for r in rows], dtype=float)


def load_prices_with_dates(conn, ticker):
    """Tuple (dates, closes) for one ticker. Both numpy arrays, oldest first."""
    rows = conn.execute(
        f"SELECT date, close FROM {T_PRICES} WHERE ticker=? ORDER BY date",
        (ticker,),
    ).fetchall()
    if not rows:
        return np.zeros(0, dtype="<U10"), np.zeros(0, dtype=float)
    ds = np.asarray([r[0] for r in rows])
    cs = np.asarray([r[1] for r in rows], dtype=float)
    return ds, cs


def load_prices_bulk(conn, tickers):
    """Return {ticker: closes} for many tickers, oldest first."""
    out = {}
    for chunk in _chunked(tickers):
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT ticker, date, close FROM {T_PRICES} "
            f"WHERE ticker IN ({ph}) ORDER BY ticker, date",
            chunk,
        ).fetchall()
        for t, _d, c in rows:
            if c is None:
                continue
            out.setdefault(t, []).append(c)
    return {t: np.asarray(v, dtype=float) for t, v in out.items()}


def load_prices_bulk_with_dates(conn, tickers):
    """Return {ticker: (dates, closes)} for many tickers."""
    out = {}
    for chunk in _chunked(tickers):
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT ticker, date, close FROM {T_PRICES} "
            f"WHERE ticker IN ({ph}) ORDER BY ticker, date",
            chunk,
        ).fetchall()
        for t, d, c in rows:
            if c is None or d is None:
                continue
            out.setdefault(t, ([], []))
            out[t][0].append(d)
            out[t][1].append(float(c))
    return {
        t: (np.asarray(ds), np.asarray(cs, dtype=float))
        for t, (ds, cs) in out.items()
    }


def load_market(conn):
    """Return (dates, closes) for the market ticker (SPY by default)."""
    return load_prices_with_dates(conn, MARKET_TICKER)


# --------------------------------------------------------------------------- #
# Financials
# --------------------------------------------------------------------------- #
def load_financials(conn, ticker):
    """Return parsed JSON record for one ticker, or None."""
    row = conn.execute(
        f"SELECT data FROM {T_FINANCIALS} WHERE ticker=?", (ticker,)
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def load_all_financials(conn):
    """Return {ticker: parsed_record} for everything in the financials table."""
    rows = conn.execute(
        f"SELECT ticker, data FROM {T_FINANCIALS}"
    ).fetchall()
    out = {}
    for t, data in rows:
        try:
            out[t] = json.loads(data)
        except Exception:
            continue
    return out


def financials_age_days(conn, ticker):
    """Days since this ticker's financials were last fetched. None if absent."""
    from datetime import datetime
    row = conn.execute(
        f"SELECT fetched_at FROM {T_FINANCIALS} WHERE ticker=?", (ticker,)
    ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row[0])
        return (datetime.utcnow() - fetched).days
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Convenience: extract canonical fields from a financials record
# --------------------------------------------------------------------------- #
def extract_fields(record):
    """Pull the fields the model cares about from a raw financials JSON.
    Returns a flat dict — same shape used by shared.compute_factors."""
    if not record:
        return {}

    inc = record.get("income") or {}
    bal = record.get("balance") or {}
    cfs = record.get("cashflow") or {}
    ev = record.get("enterprise") or {}
    prof = record.get("profile") or {}

    price = prof.get("price")
    mkt_cap = prof.get("marketCap") or prof.get("mktCap")
    shares = ev.get("numberOfShares")
    if not shares and mkt_cap and price:
        try:
            shares = mkt_cap / price
        except Exception:
            shares = None

    book_value = (
        bal.get("totalStockholdersEquity")
        or bal.get("totalEquity")
    )

    return {
        "price": price,
        "shares_outstanding": shares,
        "free_cash_flow": cfs.get("freeCashFlow"),
        "enterprise_value": ev.get("enterpriseValue"),
        "ebit": inc.get("operatingIncome") or inc.get("ebit"),
        "gross_profit": inc.get("grossProfit"),
        "operating_income": inc.get("operatingIncome"),
        "revenue": inc.get("revenue"),
        "total_assets": bal.get("totalAssets"),
        "total_debt": bal.get("totalDebt"),
        "cash_and_equivalents": (
            bal.get("cashAndCashEquivalents")
            or bal.get("cashAndShortTermInvestments")
        ),
        "book_value": book_value,
        "market_cap": mkt_cap,
        "sector": prof.get("sector") or "Unknown",
    }


# --------------------------------------------------------------------------- #
# Self-tests
# --------------------------------------------------------------------------- #
def _test_pass(label):
    print(f"  ✓ {label}")


def _test_fail(label, msg=""):
    print(f"  ✗ {label}{(': ' + msg) if msg else ''}")
    return False


def run_self_tests():
    print("=" * 56)
    print("  db.py self-tests")
    print("=" * 56)

    if not cache_exists():
        print("  FAIL: cache.db does not exist. Run cache.py first.")
        return False

    conn = open_cache(read_only=True)
    failures = 0

    universe = load_universe(conn, include_market=False)
    if len(universe) >= 1:
        _test_pass(f"load_universe: {len(universe)} tickers")
    else:
        failures += 1
        _test_fail("load_universe", "empty")

    universe_w_market = load_universe(conn, include_market=True)
    if MARKET_TICKER in universe_w_market:
        _test_pass(f"load_universe(include_market=True): {MARKET_TICKER} appended")
    else:
        failures += 1
        _test_fail("load_universe(include_market)", f"missing {MARKET_TICKER}")

    sectors = load_universe_with_sectors(conn)
    if len(sectors) == len(universe):
        _test_pass(f"load_universe_with_sectors: {len(sectors)} mapped")
    else:
        failures += 1
        _test_fail("load_universe_with_sectors", "count mismatch")

    if universe:
        t0 = universe[0]
        prices = load_prices(conn, t0)
        if prices.size > 0:
            _test_pass(f"load_prices({t0}): {prices.size} closes")
        else:
            failures += 1
            _test_fail(f"load_prices({t0})", "empty")

        ds, cs = load_prices_with_dates(conn, t0)
        if ds.size == cs.size and ds.size > 0:
            _test_pass(
                f"load_prices_with_dates({t0}): {ds.size} bars, "
                f"{ds[0]} → {ds[-1]}"
            )
        else:
            failures += 1
            _test_fail(
                f"load_prices_with_dates({t0})",
                f"shape mismatch ({ds.size} vs {cs.size})",
            )

    bulk = load_prices_bulk(conn, universe)
    if len(bulk) == len(universe):
        _test_pass(f"load_prices_bulk: {len(bulk)} tickers")
    else:
        failures += 1
        _test_fail("load_prices_bulk",
                   f"got {len(bulk)} of {len(universe)} expected")

    m_dates, m_close = load_market(conn)
    if m_close.size > 0:
        _test_pass(f"load_market ({MARKET_TICKER}): {m_close.size} bars")
    else:
        failures += 1
        _test_fail("load_market", "empty")

    if universe:
        t0 = universe[0]
        rec = load_financials(conn, t0)
        if rec and isinstance(rec, dict):
            keys = set(rec.keys())
            expected = {"income", "balance", "cashflow", "enterprise", "profile"}
            if expected.issubset(keys):
                _test_pass(f"load_financials({t0}): {sorted(keys)}")
            else:
                failures += 1
                _test_fail(
                    f"load_financials({t0})",
                    f"missing keys: {expected - keys}",
                )
        else:
            failures += 1
            _test_fail(f"load_financials({t0})", "None or not dict")

        fields = extract_fields(rec)
        required = ["price", "revenue", "total_assets", "sector"]
        missing = [k for k in required if k not in fields]
        if not missing:
            _test_pass(
                f"extract_fields({t0}): sector='{fields['sector']}', "
                f"price={fields['price']}"
            )
        else:
            failures += 1
            _test_fail("extract_fields", f"missing {missing}")

    all_fins = load_all_financials(conn)
    if len(all_fins) == len(universe):
        _test_pass(f"load_all_financials: {len(all_fins)} records")
    else:
        failures += 1
        _test_fail("load_all_financials",
                   f"got {len(all_fins)} of {len(universe)}")

    try:
        conn.execute(f"DELETE FROM {T_UNIVERSE}")
        failures += 1
        _test_fail("read-only enforcement", "DELETE succeeded (should fail)")
    except sqlite3.OperationalError:
        _test_pass("read-only enforcement: writes correctly blocked")

    conn.close()

    print("=" * 56)
    if failures == 0:
        print(f"  ALL TESTS PASSED")
    else:
        print(f"  {failures} TEST(S) FAILED")
    print("=" * 56)
    return failures == 0


if __name__ == "__main__":
    run_self_tests()
