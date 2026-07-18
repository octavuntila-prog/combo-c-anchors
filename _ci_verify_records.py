"""CI guard: every OTS-stamped record must hash to EXACTLY the digest committed
inside its .ots proof.

This is the automated form of the 2026-06-09 lesson: a checkout that rewrites
line endings (or any byte drift in a record) silently breaks the Bitcoin
attestation -- sha256(record) no longer matches the digest the calendars
committed. `.gitattributes * -text` prevents the rewrite; this check PROVES the
bytes still match on every push, on a fresh CI checkout, for every record.

Zero-results is a SIGNAL, not a pass: if no *.json.ots files are found the
script exits 1 (an empty glob would otherwise report success on a broken path).
"""
import glob
import hashlib
import sys

from opentimestamps.core.serialize import StreamDeserializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile

fails = 0
proofs = sorted(glob.glob("*.json.ots"))
if not proofs:
    print("NO *.json.ots proofs found -- SIGNAL (wrong cwd or repo layout drift)")
    sys.exit(1)

for ots_path in proofs:
    rec_path = ots_path[:-4]
    with open(ots_path, "rb") as f:
        det = DetachedTimestampFile.deserialize(StreamDeserializationContext(f))
    committed = det.timestamp.msg.hex()
    with open(rec_path, "rb") as f:
        actual = hashlib.sha256(f.read()).hexdigest()
    ok = committed == actual
    print(f"{'OK  ' if ok else 'FAIL'} {rec_path}")
    print(f"      sha256(file)  = {actual}")
    print(f"      ots-committed = {committed}")
    if not ok:
        fails += 1

print()
print("RECORDS:", "ALL MATCH" if fails == 0 else f"{fails} MISMATCH(ES) -- bytes drifted vs the stamped digest")
sys.exit(1 if fails else 0)
