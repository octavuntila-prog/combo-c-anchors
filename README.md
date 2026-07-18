# Combo C — tamper-evident anchors for the Kalshi signal radar

Independent, reproducible verification that a stream of Kalshi prediction-market signals
was committed **no later than** its recorded time — defeating *author* backdating, not
merely third-party tampering.

The mechanism is a **public SHA-256 hash chain (no secret)** rooted in a frozen corpus
whose hash is **OpenTimestamps-stamped into the Bitcoin blockchain**. Because the chain
uses no secret, anyone can independently recompute and verify it against the data — no
shared key, no trust in the author. That public verifiability is the point versus an HMAC
chain (which only the key-holder can verify).

What defeats *author* backdating is the **external Bitcoin anchor**, not secret-lessness on
its own: an author can recompute a public chain under any timestamps, but cannot match a
hash already stamped into Bitcoin. **Scope of the anchor today:** the OpenTimestamps proofs
cover the **genesis corpus and the deploy-gap (id ≤ 16,827,536)** — not the growing
per-signal Tier-A chain above the boundary (id > 16,827,536). "One external anchor on the
head covers every prior row" is the *design principle*; that head anchor is **not yet
instantiated**, so rows above the boundary currently rely on the unbroken chain back to the
anchored genesis plus the pending head anchor.

The genesis record also binds the **radar method** (`algorithm_sha256 = dee01a74…`,
`RADAR_ALGORITHM.md` as-of 2026-06-06) alongside the corpus — a pre-registration
"no later than" bound separating confirmatory from exploratory analysis: the method was
fixed before the signals it later scores.

This repository publishes everything a reviewer needs to check that claim **without
touching the author's infrastructure** — verification runs against a published snapshot
(Zenodo at paper-time, or your own copy), never a live server.

## What is anchored, and the coverage arithmetic

Every signal carries at least an existence bound, in three contiguous tiers:

| Tier | Row ids | Bound |
|------|---------|-------|
| Genesis corpus | `1 .. 16,807,130` | `corpus_sha256 = a5989f…` in `anchor_record_20260606.json`, OTS→Bitcoin |
| Gap (inter-deploy cycle) | `16,807,131 .. 16,827,536` (20,406) | `gap_sha256 = 87fa8b…` in `gap_anchor_record_20260606.json`, OTS→Bitcoin |
| Tier-A per-signal chain | `16,827,537 .. head` | each row's SHA-256 links to the prior; root = the genesis hash |

**Sanity-check (self-verifying):**

```
genesis(1 .. 16,807,130)  +  gap(16,807,131 .. 16,827,536)  =  16,827,536   (last pre-chain id)
                                                  boundary first chained  =  16,827,537
chained rows  =  max(id)  -  16,827,537  +  1          (iff null_after_boundary = 0)
```

`null_after_boundary = 0` (no unchained row past the boundary) means the chain is gapless
from 16,827,537 to the head, so the `chained = total - boundary + 1` identity holds
exactly. `chain_verify.py` prints all three numbers.

## Two-hop verification (copy-paste, any OpenTimestamps client)

The chain root is bound to Bitcoin in two hops — reproduce both:

**Hop 1 — the record contains the chain root.**

```
grep corpus_sha256 anchor_record_20260606.json
#  -> "corpus_sha256": "a5989f…"   (this IS the chain root: prev_hash of the first chained row)
```

**Hop 2 — the record's own hash is Bitcoin-attested.**

```
sha256sum anchor_record_20260606.json
#  -> 919180a9b21cd9bcf8cfdce28250aa2a7943fba5f7f9182cac02c9ce19a96174
ots verify anchor_record_20260606.json.ots
#  -> Bitcoin block 952591 / 952595 (stamped 2026-06-07)

sha256sum gap_anchor_record_20260606.json
#  -> 7dcc4ca59b5fb0187c83f2a7bc1e80f7190c38d0a4e6e1f16bac7856c37344f7
ots verify gap_anchor_record_20260606.json.ots
#  -> Bitcoin block 952650 / 952683 (stamped 2026-06-07)
```

A separate OTS stamp for the gap is structurally necessary: the genesis record is
cryptographically closed and cannot be appended retroactively.

So the trust path is **chain root `a5989f` -> contained in a record -> `sha256(record)`
-> OTS proof -> Bitcoin block**. No trust in the author, the server, or this repo — only
in SHA-256, OpenTimestamps, and Bitcoin.

## Verifying the chain itself

Run against a published snapshot (the Zenodo corpus at paper-time, or your own copy of
`kalshi_signals.db`):

```
python3 chain_verify.py path/to/kalshi_signals.db
```

It walks every chained row in id order, recomputes each SHA-256 from the stored content
columns, checks `prev_hash` links back to the genesis anchor, and reports `OK` /
`BREAK <id>`. The hash covers the 14 content columns (numeric values normalized to float
so SQLite's REAL affinity round-trips identically; titles pinned with `ensure_ascii`).

`_verify_container.py` is the operator's *live-DB* twin: the same walk plus chunked reads
and retry-on-lock, for verifying an **actively-written** DB without blocking the writer.
A reviewer does not need it — use `chain_verify.py`. The container cannot import
`kalshi_chain`, so the live-safe walk is physically duplicated there; `test_chain.py`
(`T5`) binds the two copies with an equivalence test (identical verdict on a quiescent
DB), so they cannot drift silently.

## A note on `corpus_frozen_path`

The records carry a `corpus_frozen_path` / `gap_frozen_artifact` field
(`CPX52:/home/deploy/anchors/…`). That is the **author's frozen-artifact location at
freeze time** — a server-class label (a Hetzner instance type) and a deploy-path
convention, not a routable host, a credential, or a service. **Independent verification
does NOT use it** — a reviewer runs against the published snapshot. The field is
reproduced byte-identical because it is part of the OTS-stamped payload: changing one
byte would break the Bitcoin attestation.

## Contents

| File | Role |
|------|------|
| `kalshi_chain.py` | canonical chain logic — hash + live-safe `verify_chain()` |
| `chain_verify.py` | CLI: verify a snapshot |
| `_verify_container.py` | operator's live-DB twin (chunk + retry-on-lock) |
| `test_chain.py` | chain-logic tests incl. the twin-equivalence test (`T5`) |
| `ots_stamp.py` | how the anchor records were OpenTimestamps-stamped |
| `anchor_record_20260606.json` (+ `.ots`) | genesis existence + method anchor |
| `gap_anchor_record_20260606.json` (+ `.ots`) | inter-deploy gap existence anchor |

The signal **data** (the corpus and gap rows) is **not** in this repository; it is
deposited on Zenodo at paper-time with a citable DOI. This repo publishes the
*verification* — the hashes, the Bitcoin proofs, and the scripts — so the chain is
checkable before the data is released.
