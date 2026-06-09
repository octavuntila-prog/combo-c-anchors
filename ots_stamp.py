"""Reusable OpenTimestamps stamp (library-based; the ots CLI is broken on Windows
via python-bitcoinlib/OpenSSL). Usage: python ots_stamp.py <file>  -> writes <file>.ots
"""
import sys, hashlib
from opentimestamps.core.timestamp import Timestamp, DetachedTimestampFile
from opentimestamps.core.op import OpSHA256
from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.serialize import StreamSerializationContext

rec = sys.argv[1]
data = open(rec, "rb").read()
digest = hashlib.sha256(data).digest()
print("file sha256:", digest.hex())
ts = Timestamp(digest)
ok = 0
for url in ["https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org",
            "https://finney.calendar.eternitywall.com"]:
    try:
        cts = RemoteCalendar(url).submit(digest, timeout=20)
        ts.merge(cts); ok += 1; print("calendar OK:", url)
    except Exception as e:
        print("calendar FAIL:", url, type(e).__name__, str(e)[:60])
if ok == 0:
    print("NO_CALENDAR_REACHED"); sys.exit(1)
det = DetachedTimestampFile(OpSHA256(), ts)
with open(rec + ".ots", "wb") as f:
    det.serialize(StreamSerializationContext(f))
print(f"OTS_WRITTEN: {rec}.ots ({ok} calendars)")
