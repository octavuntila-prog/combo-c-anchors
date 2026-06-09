"""Validate the Tier A chain logic on a COPY — pure, no API, no prod.

Covers: clean multi-cycle chain, 0/None numeric values (float-fix), unicode
titles (ensure_ascii), genesis link, tamper detection, and a concrete
reproduction of the int-0 bug-class proving why the float-fix is required.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalshi_chain import chain_row_hash, verify_chain, GENESIS_ANCHOR, HASH_FIELDS

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_chain.db")

SCHEMA = """CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, event_ticker TEXT, market_ticker TEXT, title TEXT, subtitle TEXT,
    probability REAL, yes_bid REAL, no_bid REAL, last_price REAL, volume REAL,
    open_interest REAL, category TEXT, status TEXT, close_time TEXT,
    prev_hash TEXT, hash TEXT)"""

INSERT_SQL = (
    "INSERT INTO signals (ts,event_ticker,market_ticker,title,subtitle,probability,"
    "yes_bid,no_bid,last_price,volume,open_interest,category,status,close_time,"
    "prev_hash,hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def fresh_db():
    if os.path.exists(DB):
        os.remove(DB)
    db = sqlite3.connect(DB)
    db.execute(SCHEMA)
    db.commit()
    return db


def norm(raw):
    """Mimic the collector patch float-fix: numeric -> float else 0.0."""
    f = lambda x: float(x) if x else 0.0
    return {
        "ts": raw["ts"], "event_ticker": raw["event_ticker"], "market_ticker": raw["market_ticker"],
        "title": raw["title"], "subtitle": raw["subtitle"],
        "probability": f(raw["probability"]), "yes_bid": f(raw["yes_bid"]), "no_bid": f(raw["no_bid"]),
        "last_price": f(raw["last_price"]), "volume": f(raw["volume"]), "open_interest": f(raw["open_interest"]),
        "category": raw["category"], "status": raw["status"], "close_time": raw["close_time"],
    }


def insert_cycle(db, raws):
    """Mimic collect(): read chain head (genesis fallback), thread prev_hash, one commit."""
    r = db.execute("SELECT hash FROM signals WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    prev = r[0] if r and r[0] else GENESIS_ANCHOR
    for raw in raws:
        row = norm(raw)
        h = chain_row_hash(row, prev)
        db.execute(INSERT_SQL, [row[k] for k in HASH_FIELDS] + [prev, h])
        prev = h
    db.commit()


R1 = {"ts": "2026-06-06T09:00:00Z", "event_ticker": "KXAI-26", "market_ticker": "KXAI-26-Y",
      "title": "AI Act enforcement", "subtitle": "Will Art.50 apply", "probability": 0.42,
      "yes_bid": 0.41, "no_bid": 0.59, "last_price": 0.42, "volume": 1000.0, "open_interest": 500.0,
      "category": "Politics", "status": "active", "close_time": "2026-12-31"}
# edge: 0 / None numerics + unicode text (float-fix + ensure_ascii)
R2 = {"ts": "2026-06-06T09:00:00Z", "event_ticker": "KXIPO-26", "market_ticker": "KXIPO-26-Y",
      "title": "Société Générale IPO — 5€", "subtitle": "café",
      "probability": 0, "yes_bid": None, "no_bid": 0, "last_price": None, "volume": 0,
      "open_interest": 0, "category": "Companies", "status": "active", "close_time": ""}
R3 = {"ts": "2026-06-06T10:00:00Z", "event_ticker": "KXAI-26", "market_ticker": "KXAI-26-Y",
      "title": "AI Act enforcement", "subtitle": "Will Art.50 apply", "probability": 0.45,
      "yes_bid": 0.44, "no_bid": 0.56, "last_price": 0.45, "volume": 1200.0, "open_interest": 550.0,
      "category": "Politics", "status": "active", "close_time": "2026-12-31"}

fails = 0


def check(name, cond, extra=""):
    global fails
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -  {extra}" if extra else ""))
    if not cond:
        fails += 1


# TEST 1: clean multi-cycle chain (0-values + unicode) -> GREEN
db = fresh_db()
insert_cycle(db, [R1, R2])   # cycle 1
insert_cycle(db, [R3])       # cycle 2 (continues the chain across a commit boundary)
db.close()
ok, msg, brk = verify_chain(DB)
check("T1 clean chain (0-val + unicode + 2 cycles)", ok, msg)

# TEST 2: genesis link — row 1 prev_hash == GENESIS_ANCHOR
con = sqlite3.connect(DB)
first_prev = con.execute("SELECT prev_hash FROM signals ORDER BY id LIMIT 1").fetchone()[0]
con.close()
check("T2 genesis link (row1.prev == a5989f corpus)", first_prev == GENESIS_ANCHOR)

# TEST 3: tamper detection — flip a stored value, chain must catch it
con = sqlite3.connect(DB)
con.execute("UPDATE signals SET probability=0.99 WHERE id=1")
con.commit()
con.close()
ok, msg, brk = verify_chain(DB)
check("T3 tamper detected at id=1", (not ok) and brk == 1, msg)

# TEST 4a: reproduce the int-0 bug — hash computed with int 0, stored as REAL 0.0 -> false positive
db = fresh_db()
buggy = norm(R2)
for k in ("probability", "yes_bid", "no_bid", "last_price", "volume", "open_interest"):
    buggy[k] = 0   # int 0, NOT 0.0 (the bug)
hb = chain_row_hash(buggy, GENESIS_ANCHOR)        # json.dumps(0) -> "0"
db.execute(INSERT_SQL, [buggy[k] for k in HASH_FIELDS] + [GENESIS_ANCHOR, hb])
db.commit()
db.close()
ok_b, msg_b, _ = verify_chain(DB)                  # reads REAL 0.0 -> json.dumps(0.0) -> "0.0"
check("T4a int-0 bug reproduces false-positive (proves the fix is needed)", not ok_b, msg_b)

# TEST 4b: float-fix version verifies green
db = fresh_db()
fixed = norm(R2)                                   # norm() -> float else 0.0
hf = chain_row_hash(fixed, GENESIS_ANCHOR)
db.execute(INSERT_SQL, [fixed[k] for k in HASH_FIELDS] + [GENESIS_ANCHOR, hf])
db.commit()
db.close()
ok_f, msg_f, _ = verify_chain(DB)
check("T4b float-fix verifies green on same 0-value row", ok_f, msg_f)

# TEST 5: equivalence with the container twin (_verify_container.py). The two physical
# copies of the live-safe walk MUST agree on the same quiescent DB, else they drift over
# time (the reason the duplication is bound by a test, not just a comment).
import importlib
_vc = importlib.import_module("_verify_container")
db = fresh_db()
insert_cycle(db, [R1, R2])
insert_cycle(db, [R3])
db.close()
ok1, msg1, _ = verify_chain(DB)
ok2, head2, n2, nab2 = _vc.check(DB)
check("T5 twin equivalence: same ok verdict", ok1 == ok2 == True)
check("T5 twin equivalence: same chained-count (3)", n2 == 3 and "3 rows chain-verified" in msg1,
      f"n2={n2} msg1={msg1}")
check("T5 twin equivalence: same head", head2[:16] in msg1, f"head2={head2[:16]} msg1={msg1}")
_here = os.path.dirname(os.path.abspath(__file__))
for nm in ("kalshi_chain.py", "_verify_container.py"):
    src = open(os.path.join(_here, nm)).read()
    check(f"T5 {nm} keeps chunking (LIMIT)", "LIMIT" in src)
    check(f"T5 {nm} keeps retry-on-lock (locked + sleep)", "locked" in src and "sleep" in src)

if os.path.exists(DB):
    os.remove(DB)
print()
print("RESULT:", "ALL GREEN" if fails == 0 else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
