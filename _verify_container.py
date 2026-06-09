"""Live-DB-safe one-shot chain check WITH retry-on-lock, run INSIDE the collector
container (the operator's twin of chain_verify.py). A REVIEWER does NOT need this --
run chain_verify.py on the published snapshot instead; this script exists for verifying
the chain against a *live*, actively-written DB.

    KALSHI_DB=/path/to/kalshi_signals.db
    ssh <HOST> 'docker exec -i -e KALSHI_DB <CONTAINER> python3' < _verify_container.py

The live kalshi_signals.db is ROLLBACK-JOURNAL mode (not WAL), so a `mode=ro` connection
cannot open it while the collector holds a write lock. This uses a NORMAL connection but
issues ONLY SELECTs (no writes), walks the chain in CHUNKS (releasing the read lock
between chunks so the collector is never blocked for more than one chunk read), and
RETRIES with backoff when an active write cycle transiently yields "database is locked".
"""
import sqlite3, hashlib, json, os, time

# TWIN of kalshi_chain.verify_chain(): the live container cannot import kalshi_chain, so
# the live-safe walk is duplicated here. Kept in sync by
# test_chain.py::test_verify_equivalence_with_container_twin -- do not edit one alone.
GENESIS = "a5989faaa895a642b0b7e4cd9ec21d7c19bb5e092fb5227951269b2293ef9853"
FIELDS = ["ts", "event_ticker", "market_ticker", "title", "subtitle", "probability",
          "yes_bid", "no_bid", "last_price", "volume", "open_interest", "category",
          "status", "close_time"]
BOUNDARY = 16827536   # first chained row is 16,827,537


def rh(row, prev):
    p = {k: row[k] for k in FIELDS}
    p["prev"] = prev
    return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def check(db_path=None):
    db = sqlite3.connect(
        db_path or os.environ.get("KALSHI_DB", "kalshi_signals.db"),
        timeout=180,
    )  # SELECT-only below
    try:
        tot = db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        ch = db.execute("SELECT COUNT(*) FROM signals WHERE hash IS NOT NULL").fetchone()[0]
        nab = db.execute("SELECT COUNT(*) FROM signals WHERE id>? AND hash IS NULL", (BOUNDARY,)).fetchone()[0]
        fb = db.execute("SELECT MIN(id) FROM signals WHERE hash IS NOT NULL").fetchone()[0]
        mts = db.execute("SELECT MAX(ts) FROM signals").fetchone()[0]
        print(f"total={tot:,} chained={ch:,} null_after_boundary={nab} boundary_first={fb} max_ts={mts}")

        cols = ",".join(FIELDS)
        prev = GENESIS
        n = 0
        bad = None
        last = 0
        t0 = time.time()
        while True:
            rows = db.execute(f"SELECT id,{cols},prev_hash,hash FROM signals "
                              f"WHERE hash IS NOT NULL AND id>? ORDER BY id LIMIT 100000", (last,)).fetchall()
            if not rows:
                break
            for r in rows:
                rid = r[0]
                row = {k: r[i + 1] for i, k in enumerate(FIELDS)}
                sp, sh = r[-2], r[-1]
                if sp != prev:
                    bad = (rid, "prev_link", str(sp)[:16], str(prev)[:16]); break
                if rh(row, prev) != sh:
                    bad = (rid, "hash", rh(row, prev)[:16], str(sh)[:16]); break
                prev = sh
                n += 1
                last = rid
            if bad:
                break
        dt = time.time() - t0
        if bad:
            print(f"CHAIN BREAK at id={bad[0]} ({bad[1]}): got={bad[2]} exp={bad[3]}")
        else:
            print(f"CHAIN OK: {n:,} rows from genesis; head={prev[:16]} ({dt:.1f}s)")
        print("HEALTH:", "GREEN" if (not bad and nab == 0) else "CHECK-NEEDED")
        return (not bad, prev, n, nab)  # (ok, head, chained_count, null_after_boundary)
    finally:
        db.close()


# The collector (rollback-journal mode) holds EXCLUSIVE during a write cycle, so a
# read can transiently hit "database is locked". Retry with backoff until a read
# window opens (10/20/30/40/50s). Guarded so importing this module (the equivalence
# test) does not run the live check; `python3 < _verify_container.py` still does.
if __name__ == "__main__":
    for attempt in range(6):
        try:
            check()
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 5:
                wait = 10 * (attempt + 1)
                print(f"[database is locked — collector mid-write; retry {attempt + 1}/5 in {wait}s]")
                time.sleep(wait)
                continue
            raise
