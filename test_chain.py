"""Validate the Tier A chain logic on a COPY — pure, no API, no prod.

Covers: clean multi-cycle chain, 0/None numeric values (float-fix), unicode
titles (ensure_ascii), genesis link, tamper detection, a concrete
reproduction of the int-0 bug-class proving why the float-fix is required,
and (T5/T6) the equivalence bond across ALL physical copies of the hash core:
the public twin (kalshi_chain.py / _verify_container.py) plus — when run on
the operator machine — the two local-only copies (_snapshot_verify.py PRIMARY
verifier and the collector's embedded _chain_hash), extending the twin to a
QUADRUPLET (audit 2026-07-17 item #7).
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

# TEST 6: QUADRUPLET equivalence — extend the twin bond (T5) to the two LOCAL-ONLY
# copies of the hash core: _snapshot_verify.py (the PRIMARY morning-check verifier)
# and the collector's embedded _chain_hash (kalshi_collector_container.py). Until
# this test both were protected only by "keep byte-identical" comments (audit
# 2026-07-17 item #7: comment-only, zero tests). The bond pins the FUNCTIONAL core
# (constants + hash behaviour + walk verdict), NOT whole-file bytes: the public
# _verify_container.py intentionally differs from the operational copy in
# docstring/default-path (sanitized for publication) and must not false-alarm.
#
# Presence policy (no silent skips): the two files live OUTSIDE the public repo.
#   found     -> full equivalence; any mismatch = FAIL
#   not found -> explicit SKIP line per file; FAIL only if COMBO_C_REQUIRE_QUADRUPLET=1
#                (the operator morning check sets it; a public/CI checkout does not).
import ast
import importlib.util

# Pinned IN-TEST so a coordinated edit of all four sources still trips here.
PIN_GENESIS = "a5989faaa895a642b0b7e4cd9ec21d7c19bb5e092fb5227951269b2293ef9853"
PIN_FIELDS = ["ts", "event_ticker", "market_ticker", "title", "subtitle",
              "probability", "yes_bid", "no_bid", "last_price", "volume",
              "open_interest", "category", "status", "close_time"]
PIN_BOUNDARY = 16827536


def _find_local(name):
    """COMBO_C_LOCAL_DIR override, then the operational sibling ../combo-c-anchors
    (equal to the script dir when running FROM the operational dir), then the script
    dir itself. Sibling-BEFORE-here so a stray debug copy left in the public checkout
    can never silently shadow the operational file; the caller prints a BOND
    provenance line with the resolved path for the same reason."""
    cands = []
    env_dir = os.environ.get("COMBO_C_LOCAL_DIR")
    if env_dir:
        cands.append(os.path.join(env_dir, name))
    cands.append(os.path.join(os.path.dirname(_here), "combo-c-anchors", name))
    cands.append(os.path.join(_here, name))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _extract_collector_core(path):
    """AST-extract GENESIS_ANCHOR + _HASH_FIELDS + _chain_hash from the collector
    WITHOUT importing it (module import needs httpx and runs logging setup).
    Executing the real extracted AST nodes (not a regex copy) keeps the bond on
    the actual deployed code."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in ("GENESIS_ANCHOR", "_HASH_FIELDS")
                for t in node.targets):
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_chain_hash":
            keep.append(node)
    import hashlib as _hl
    import json as _js
    ns = {"hashlib": _hl, "json": _js}
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), ns)
    missing = [k for k in ("GENESIS_ANCHOR", "_HASH_FIELDS", "_chain_hash") if k not in ns]
    return ns, missing


_req_quad = os.environ.get("COMBO_C_REQUIRE_QUADRUPLET") == "1"
_vec_rows = [norm(R1), norm(R2), norm(R3)]   # incl. the 0.0/unicode edge row

# 6a: pin the PUBLIC pair itself (T5 compares the twins to each other but pins
# nothing — a coordinated rewrite of both would previously have passed).
check("T6 canonical kalshi_chain GENESIS_ANCHOR == pinned", GENESIS_ANCHOR == PIN_GENESIS)
check("T6 canonical kalshi_chain HASH_FIELDS == pinned", list(HASH_FIELDS) == PIN_FIELDS)
check("T6 _verify_container GENESIS/FIELDS/BOUNDARY == pinned",
      _vc.GENESIS == PIN_GENESIS and list(_vc.FIELDS) == PIN_FIELDS
      and _vc.BOUNDARY == PIN_BOUNDARY)

# 6b: _snapshot_verify.py — the PRIMARY morning-check verifier.
_sv_path = _find_local("_snapshot_verify.py")
if _sv_path is None:
    print("  SKIP  T6 _snapshot_verify.py not present (public-only checkout) — quadruplet reduced to twin")
    if _req_quad:
        check("T6 REQUIRE_QUADRUPLET: _snapshot_verify.py must be present", False)
else:
    print(f"  BOND  T6 _snapshot_verify.py <- {_sv_path}")
    _spec = importlib.util.spec_from_file_location("_sv_quad", _sv_path)
    _sv = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sv)
    check("T6 _snapshot_verify GENESIS == pinned", _sv.GENESIS == PIN_GENESIS)
    check("T6 _snapshot_verify FIELDS == pinned", list(_sv.FIELDS) == PIN_FIELDS)
    check("T6 _snapshot_verify BOUNDARY == pinned", _sv.BOUNDARY == PIN_BOUNDARY)
    _prev = PIN_GENESIS
    _ok_h = True
    for _row in _vec_rows:
        if chain_row_hash(_row, _prev) != _sv.rh(_row, _prev):
            _ok_h = False
            break
        _prev = chain_row_hash(_row, _prev)
    check("T6 _snapshot_verify rh() == canonical hash on vectors (0.0 + unicode)", _ok_h)
    # e2e: the PRIMARY single-pass static walk and the live-safe chunked walk must
    # return the identical verdict tuple on the same quiescent DB.
    db = fresh_db()
    insert_cycle(db, [R1, R2])
    insert_cycle(db, [R3])
    db.close()
    _ok_s, _head_s, _n_s, _nab_s = _sv.check(DB.replace(os.sep, "/"))
    _ok_v, _head_v, _n_v, _nab_v = _vc.check(DB)
    check("T6 e2e: snapshot-verify == container walk (ok, head, n, nab)",
          (_ok_s, _head_s, _n_s, _nab_s) == (_ok_v, _head_v, _n_v, _nab_v),
          f"sv=({_ok_s},{str(_head_s)[:16]},{_n_s},{_nab_s}) vc=({_ok_v},{str(_head_v)[:16]},{_n_v},{_nab_v})")
    check("T6 e2e clean verdict is GREEN (ok=True, nab=0), not just equal", _ok_s is True and _nab_s == 0)
    # RED-PATH legs (adversarial panel 2026-07-18): on clean data a rubber-stamping
    # walker returns the same tuple as a checking one, and a nab-query that always
    # returns 0 matches a correct one — so DETECTION itself must be exercised.
    # nab leg: one explicit beyond-BOUNDARY row with hash NULL. The chain walk skips
    # it (WHERE hash IS NOT NULL) but nab MUST count it in BOTH walkers — this is
    # the sole detector for "collector stopped hashing new rows".
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO signals (id, ts) VALUES (?, ?)",
                (PIN_BOUNDARY + 1, "2026-06-06T11:00:00Z"))
    con.commit()
    con.close()
    _ok_s2, _, _n_s2, _nab_s2 = _sv.check(DB.replace(os.sep, "/"))
    _ok_v2, _, _n_v2, _nab_v2 = _vc.check(DB)
    check("T6 red-path: null-after-boundary counted by BOTH walkers (nab=1, walk still ok, n=3)",
          _ok_s2 is True and _ok_v2 is True and _n_s2 == _n_v2 == 3 and _nab_s2 == _nab_v2 == 1,
          f"sv=(ok={_ok_s2},n={_n_s2},nab={_nab_s2}) vc=(ok={_ok_v2},n={_n_v2},nab={_nab_v2})")
    # tamper leg: flip stored content in row 1 (same tamper class as T3) — BOTH
    # local walkers must go RED, proving their detection branches exist and fire.
    con = sqlite3.connect(DB)
    con.execute("UPDATE signals SET probability=0.99 WHERE id=1")
    con.commit()
    con.close()
    _ok_s3 = _sv.check(DB.replace(os.sep, "/"))[0]
    _ok_v3 = _vc.check(DB)[0]
    check("T6 red-path: tamper detected by BOTH walkers (ok=False)",
          _ok_s3 is False and _ok_v3 is False, f"sv_ok={_ok_s3} vc_ok={_ok_v3}")

# 6c: the collector's embedded _chain_hash — the WRITE-side copy.
_col_path = _find_local("kalshi_collector_container.py")
if _col_path is None:
    print("  SKIP  T6 kalshi_collector_container.py not present (public-only checkout) — quadruplet reduced to twin")
    if _req_quad:
        check("T6 REQUIRE_QUADRUPLET: kalshi_collector_container.py must be present", False)
else:
    print(f"  BOND  T6 kalshi_collector_container.py <- {_col_path}")
    _ns, _missing = _extract_collector_core(_col_path)
    check("T6 collector core extracted (GENESIS_ANCHOR, _HASH_FIELDS, _chain_hash)",
          not _missing, f"missing={_missing}" if _missing else "")
    if not _missing:
        check("T6 collector GENESIS_ANCHOR == pinned", _ns["GENESIS_ANCHOR"] == PIN_GENESIS)
        check("T6 collector _HASH_FIELDS == pinned", list(_ns["_HASH_FIELDS"]) == PIN_FIELDS)
        _prev = PIN_GENESIS
        _ok_h = True
        for _row in _vec_rows:
            if chain_row_hash(_row, _prev) != _ns["_chain_hash"](_row, _prev):
                _ok_h = False
                break
            _prev = chain_row_hash(_row, _prev)
        check("T6 collector _chain_hash() == canonical hash on vectors (0.0 + unicode)", _ok_h)

if os.path.exists(DB):
    os.remove(DB)
print()
print("RESULT:", "ALL GREEN" if fails == 0 else f"{fails} FAILURE(S)")
sys.exit(1 if fails else 0)
