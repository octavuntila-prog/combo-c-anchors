#!/usr/bin/env python3
"""Verify the Tier A tamper-evident chain on a Kalshi signals DB.

Usage:
    python3 chain_verify.py [path/to/kalshi_signals.db]

Walks all chained rows (hash IS NOT NULL) in id order, recomputes each row's
SHA-256 from its stored fields, and checks prev_hash links back to the genesis
anchor. Exit 0 = chain intact, 1 = broken (prints the first breaking row id).

Genesis anchor a5989f... = SHA-256 of kalshi_genesis_20260606.db, the frozen
2026-06-06 corpus (16,807,130 signals), OpenTimestamps-stamped that day inside
anchor_record_20260606.json (+ .ots proof). Two-hop verification a reviewer can
reproduce independently:
    chain root (a5989f, in this script)
      -> contained in anchor_record_20260606.json
      -> that record's SHA-256 is OTS-stamped (Bitcoin) => externally timestamped.
Any rewrite of a row before an anchored head breaks the recomputed chain here.
The hash uses NO secret (public SHA-256) — so the author cannot regenerate the
chain to fit backdated timestamps; that is the whole point versus an HMAC chain.
"""
import sys

from kalshi_chain import verify_chain, GENESIS_ANCHOR


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "kalshi_signals.db"
    print(f"chain_verify — {db}")
    print(f"genesis anchor: {GENESIS_ANCHOR}")
    ok, summary, first_break = verify_chain(db)
    print(("OK    " if ok else "BREAK ") + summary)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
