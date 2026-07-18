"""Tier A chain logic for Kalshi signals — pre-registration (SHA-256, no secret).

Shared canonical logic used by BOTH the collector patch (embedded copy) and
chain_verify.py. Keep the two copies byte-identical to avoid verify drift.

Threat model: defeat AUTHOR backdating, not just third-party tampering.
=> public SHA-256 hash chain (no secret -> anyone can recompute + verify against
   the data; no shared key, no trust in the author -- vs an HMAC chain only the
   key-holder can verify). Secret-lessness alone does NOT stop backdating: an
   author can recompute a public chain under any timestamps. The EXTERNAL anchor
   is what pins time -- a hash stamped into Bitcoin cannot be matched to altered
   content.
   + external anchoring (OpenTimestamps -> Bitcoin). By design one head anchor
   covers all prior rows via the chain; today the instantiated anchors are the
   genesis + gap (id <= 16,827,536) and the growing head awaits its own anchor.
"""
import hashlib
import json

# Genesis root: SHA-256 of the frozen corpus (kalshi_genesis_20260606.db),
# OTS-stamped 2026-06-06 inside anchor_record_20260606.json. The first chained
# signal links to this -> chain root = the timestamped frozen corpus.
GENESIS_ANCHOR = "a5989faaa895a642b0b7e4cd9ec21d7c19bb5e092fb5227951269b2293ef9853"

# Content columns covered by the hash, in INSERT order.
# id is EXCLUDED (local rowid, not content). chain order = insert order = id order.
HASH_FIELDS = [
    "ts", "event_ticker", "market_ticker", "title", "subtitle",
    "probability", "yes_bid", "no_bid", "last_price", "volume",
    "open_interest", "category", "status", "close_time",
]


def chain_row_hash(row, prev_hash):
    """SHA-256 of a signal row chained to prev_hash.

    Numeric fields MUST already be Python floats (caller normalizes with
    `float(x) if x else 0.0` — never bare int 0). Reason: SQLite REAL affinity
    stores 0 as 0.0, so verify-time reads back 0.0; if insert-time hashed int 0
    (json.dumps(0)=="0") the recompute (json.dumps(0.0)=="0.0") would mismatch
    and raise a false-positive tampering alert. ensure_ascii=True pins unicode
    titles to identical \\uXXXX escapes in both directions.
    """
    payload = {k: row[k] for k in HASH_FIELDS}
    payload["prev"] = prev_hash
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _short(h):
    return (h[:16] + "…") if h and len(h) > 16 else str(h)


def verify_chain(db_path, chunk=100000, retries=5):
    """Walk chained signals in id order, recompute each hash, check prev links.

    Returns (ok: bool, summary: str, first_break_id: int | None).

    LIVE-SAFE: the live kalshi_signals.db is ROLLBACK-JOURNAL mode (not WAL), so a
    ``file:...?mode=ro`` connection cannot open it while the collector holds a write
    lock. This opens a NORMAL connection but issues ONLY SELECTs (no writes), walks the
    chain in CHUNKS (releasing the read lock between chunks so the collector is never
    blocked for more than one chunk), and RETRIES with backoff (10/20/30/40/50s) on a
    transient "database is locked". On a quiescent snapshot the retry never fires.

    TWIN of ``_verify_container.py``'s inline ``check()``: the live container cannot
    import this module, so the live-safe walk is duplicated there. The two copies are
    kept in sync by ``test_chain.py::test_verify_equivalence_with_container_twin`` (same
    quiescent DB -> identical (ok, head, chained-count)); do not edit one without the
    other.
    """
    import sqlite3
    import time

    cols = ",".join(HASH_FIELDS)
    for attempt in range(retries + 1):
        db = sqlite3.connect(db_path, timeout=180)  # normal conn; SELECT-only below
        try:
            prev = GENESIS_ANCHOR
            n = 0
            last = 0
            while True:
                rows = db.execute(
                    f"SELECT id,{cols},prev_hash,hash FROM signals "
                    f"WHERE hash IS NOT NULL AND id>? ORDER BY id LIMIT ?",
                    (last, chunk),
                ).fetchall()
                if not rows:
                    break
                for r in rows:
                    rid = r[0]
                    row = {k: r[i + 1] for i, k in enumerate(HASH_FIELDS)}
                    stored_prev, stored_hash = r[-2], r[-1]
                    if stored_prev != prev:
                        return (False,
                                f"row id={rid}: prev_hash link broken "
                                f"(stored={_short(stored_prev)} expected={_short(prev)})",
                                rid)
                    h = chain_row_hash(row, prev)
                    if h != stored_hash:
                        return (False,
                                f"row id={rid}: hash mismatch "
                                f"(recomputed={_short(h)} stored={_short(stored_hash)})",
                                rid)
                    prev = stored_hash
                    n += 1
                    last = rid
            return True, f"{n} rows chain-verified; head={_short(prev)}", None
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        finally:
            db.close()
