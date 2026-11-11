#!/usr/bin/env python3
"""Generate one synthetic UC1 / Submarine UAT dataset for any number of banks.

    python generate.py <mapping.csv> [--rows-per-bank N] [--out <run folder>]

<mapping.csv> lists the participating banks: header bic,bank_name,bank_id, BIC8 only.
Every bank_id in it is a participating bank, in the order it first appears. A run writes
one NEW folder (default generated_datasets/<time>_n<banks>_r<N>_<mapping>/), never
overwrites one, re-reads what it wrote, asserts every invariant listed in the dataset
README and prints the counters quoted there.

Deterministic: the RNG is seeded from the mapping bytes and N and the data never reads
the clock, so the same mapping and N give byte-identical files (only the default folder
name carries a timestamp). Standard library only.
"""
import argparse
import csv
import io
import itertools
import math
import os
import random
import re
import shutil
import string
import sys
import time
from collections import Counter, defaultdict
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))

# The only MO list, shared by every bank -- no external MO list is read or written.
MOS = [
    "Phishing", "Phishing & Schadsoftware", "CEO Fraud", "Love Scam", "Anlagebetrug",
    "Enkeltrick", "Warenbetrug", "Trickbetrug", "Vorschussbetrug", "Krypto-Betrug",
    "Account Takeover", "SIM Swap Fraud", "Fake Support Call", "Instant Payment Fraud",
    "Fake Shop/Goods Fraud", "Kontoübernahme", "Identitätsdiebstahl",
    "Fremdzugriff - ungeprüft", "Betrug, unspezifiziert", "Überweisung, noch unbekannter MO",
    "Smishing", "Vishing", "Quishing (QR-Code-Phishing)", "Spoofing", "Call-ID-Spoofing",
    "Social Engineering", "Pig Butchering", "Business E-Mail Compromise (BEC)",
    "Rechnungsbetrug", "Invoice Redirection Fraud", "Mietbetrug", "Fake-Jobangebot",
    "Finanzagent / Money Mule", "Kartenbetrug", "Skimming", "Lastschriftbetrug", "Scheckbetrug",
    "Kreditbetrug", "Gewinnspielbetrug", "Falsche Polizeibeamte", "Schockanruf",
    "Hallo-Mama-Betrug", "Fake-Bankmitarbeiter", "Authorised Push Payment (APP) Fraud",
    "Fernzugriffsbetrug (AnyDesk/TeamViewer)", "Malware", "Synthetic Identity Fraud",
    "Urkundenfälschung", "Kleinanzeigenbetrug", "Paket-Phishing", "Spendenbetrug", "Sextortion",
    "Fake-Trading-Plattform", "Wangiri / Ping Call", "Insider Fraud", "Refund Fraud",
    "Echtzeitüberweisung - nicht autorisiert", "Gefälschter Überweisungsträger",
    "Karte gestohlen, PIN ausgespäht", "Zugangsdaten abgefischt, Konto leergeräumt",
    "Anlagebetrug: Festgeld 8% p.a.",
]
MO_COMMA = "Überweisung, noch unbekannter MO"
MO_NON_ASCII = "Fremdzugriff - ungeprüft"
MO_SHARED = "CEO Fraud"
# ponytail: one shared list - give each bank a seeded subset if per-bank MO variety is needed.

# Holders outside the participating banks; any BIC the mapping contains is dropped.
OUTSIDE_CANDIDATES = ["GENODEFF", "HYVEDEMM", "SOGEDEFX", "BNPAFRPP", "INGBNL2A", "CITIUS33",
                      "BARCGB22", "UBSWCHZH", "ABNANL2A", "BSCHESMM", "NDEADKKK", "RZBAATWW"]

BIC8_RE = re.compile(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}")             # BIC8 only, by design
_C = r"[A-Za-z0-9äöüÄÖÜß&\-()./,_+#'\"%:`]+"                       # platform MO validator regex
MO_RE = re.compile(rf"^{_C}( {_C})*( ?; ?{_C}( {_C})*)*(?<![,;])$")

# One weekly cycle: Mon 2026-11-02 00:00 UTC + 7 days.
T0 = 1793577600
T_NAMED = T0 + 3_600                        # named accounts: one 600 s slot each
T_NATURAL = (T0 + 20_000, T0 + 580_000)     # bulk rows: distinct random seconds
T_TIED = (T0 + 590_000, T0 + 604_800)       # one second per tied account, above every natural time
# ponytail: fixed bands - at most 560,000 natural rows and 14,800 tied accounts (about n x N <= 560k).
# The run stops before writing anything if a plan needs more; widen the bands to go bigger.


def fail(msg):
    sys.exit(f"error: {msg}")


ap = argparse.ArgumentParser(description="Generate one synthetic UC1 / Submarine UAT dataset.")
ap.add_argument("mapping", help="bank/BIC mapping CSV with header bic,bank_name,bank_id (BIC8 only)")
ap.add_argument("--rows-per-bank", type=int, default=5000, metavar="N",
                help="rows in every bank's file (default 5000)")
ap.add_argument("--out", help="run folder to create; must not exist "
                              "(default generated_datasets/<time>_n<banks>_r<N>_<mapping>)")
args = ap.parse_args()
N = args.rows_per_bank

# --- read and validate the mapping (nothing is written before this passes) -------------
with open(args.mapping, "rb") as f:
    MAPPING_BYTES = f.read()
reader = csv.DictReader(io.StringIO(MAPPING_BYTES.decode("utf-8-sig"), newline=""))
if reader.fieldnames != ["bic", "bank_name", "bank_id"]:
    fail(f"mapping header must be bic,bank_name,bank_id, got {','.join(reader.fieldnames or [])}")
MAPPING = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]

bad = [f"line {i}: {r['bic']!r}" for i, r in enumerate(MAPPING, 2) if not BIC8_RE.fullmatch(r["bic"])]
if bad:
    fail("BIC8 only - these are not 8-character BICs:\n  " + "\n  ".join(bad))
dup = sorted(b for b, c in Counter(r["bic"] for r in MAPPING).items() if c > 1)
if dup:
    fail(f"BICs listed more than once: {', '.join(dup)}")
IDS = list(dict.fromkeys(r["bank_id"] for r in MAPPING))        # roster order = first appearance
bad = [b for b in IDS if not re.fullmatch(r"[a-z0-9_]+", b)]
if bad:
    fail(f"bank_id must be lower-case letters, digits or _ (it names a file): {bad}")
names = defaultdict(set)
for r in MAPPING:
    names[r["bank_id"]].add(r["bank_name"])
bad = {b: sorted(s) for b, s in names.items() if len(s) != 1 or "" in s}
if bad:
    fail(f"each bank_id needs exactly one non-empty bank_name: {bad}")
NAME = {b: next(iter(names[b])) for b in IDS}
if len(set(NAME.values())) != len(NAME):
    fail("two bank_ids share one bank_name")
n = len(IDS)
if not 3 <= n <= 99:                       # ponytail: no 2-bank mode; 99 = the 2-digit n in account numbers
    fail(f"need 3 to 99 banks, the mapping has {n}")
if N < 1:
    fail("--rows-per-bank must be positive")
BICS = {b: [r["bic"] for r in MAPPING if r["bank_id"] == b] for b in IDS}
MAPPED = {r["bic"] for r in MAPPING}
OUTSIDE = [b for b in OUTSIDE_CANDIDATES if b not in MAPPED]
if len(OUTSIDE) < 6:
    fail(f"only {len(OUTSIDE)} outside BICs left after removing the mapping's BICs, need 6")
assert all(MO_RE.match(m) for m in MOS) and len(set(MOS)) == len(MOS)
UPPER = "sparkasse" if "sparkasse" in IDS else IDS[-1]          # the bank that writes TRUE/FALSE

# --- named scenario accounts (counters 1..16), built from roster positions ---------------
# (label, holding BIC, [(bank, seconds after slot start, MO, priority)], expected)
B0, B1, B2 = IDS[:3]
TIE = next(((x, y) for x, y in combinations(IDS, 2) if NAME[y] < NAME[x]), (B1, B2))
NAMED = [
    ("S2 corroborating report, 2 banks", BICS[B0][0],
     [(B0, 0, "Phishing", False), (B1, 60, "Phishing & Schadsoftware", False)],
     {"reports": 2, "priority": False, "banks": [B0, B1]}),
    (f"Held at another participating bank ({B1}'s BIC), reported only by {B2}", BICS[B1][-1],
     [(B2, 0, "Phishing", False)],
     {"reports": 1, "banks": [B2]}),
    ("Held outside the participating banks (BIC not in the mapping)", OUTSIDE[0],
     [(B1, 0, "Account Takeover", False)],
     {"reports": 1}),
    ("Priority OR: one True among three", BICS[B1][0],
     [(B0, 0, "Anlagebetrug", False), (B1, 60, "SIM Swap Fraud", False), (B2, 120, "Warenbetrug", True)],
     {"reports": 3, "priority": True}),
    ("Priority: all False", BICS[B2][0],
     [(B0, 0, "Warenbetrug", False), (B1, 60, "Fake Support Call", False), (B2, 120, "Enkeltrick", False)],
     {"reports": 3, "priority": False}),
    ("Priority: all True", BICS[B0][-1],
     [(B0, 0, "Phishing & Schadsoftware", True), (B1, 60, "Krypto-Betrug", True), (B2, 120, "Phishing", True)],
     {"reports": 3, "priority": True}),
    ("Several MOs in one row", BICS[B0][len(BICS[B0]) // 2],
     [(B0, 0, "Phishing & Schadsoftware;Enkeltrick;Anlagebetrug", False)],
     {"reports": 1, "mo_union": ["Anlagebetrug", "Enkeltrick", "Phishing & Schadsoftware"]}),
    ("MO containing a comma stays one MO", BICS[B0][-1],
     [(B0, 0, MO_COMMA, False)],
     {"reports": 1, "mo_union": [MO_COMMA]}),
    ("Non-ASCII MO (UTF-8 round trip)", BICS[B1][-1],
     [(B1, 0, MO_NON_ASCII, False)],
     {"reports": 1, "mo_union": [MO_NON_ASCII]}),
    (f"MO union dedup across banks (both say {MO_SHARED})", OUTSIDE[1],
     [(B0, 0, MO_SHARED, False), (B1, 60, MO_SHARED, False)],
     {"reports": 2, "mo_union": [MO_SHARED]}),
    ("Tied first-reported time, 2 banks: report groups fall back to display name"
     + ("; the roster order is the opposite" if NAME[TIE[1]] < NAME[TIE[0]] else ""), OUTSIDE[2],
     [(TIE[0], 0, "Love Scam", False), (TIE[1], 0, "Love Scam", False)],
     {"reports": 2, "banks": sorted(TIE, key=NAME.get)}),
    ("Exactly 3 reporters (BUG-005 boundary)", OUTSIDE[3],
     [(B0, 0, "Vorschussbetrug", False), (B1, 60, "Instant Payment Fraud", False), (B2, 120, "Trickbetrug", False)],
     {"reports": 3}),
    ("Singleton baseline", BICS[B2][-1],
     [(B2, 0, "Love Scam", False)],
     {"reports": 1, "priority": False}),
    (f"{UPPER} writes TRUE in upper case", BICS[UPPER][0],
     [(UPPER, 0, "Identitätsdiebstahl", True)],
     {"reports": 1, "priority": True}),
]
if n >= 4:
    NAMED.append(("4 reporters, above the BUG-005 cap (S12)", BICS[IDS[3]][0],
                  [(b, 5 * i, MOS[i], False) for i, b in enumerate(IDS[:4])], {"reports": 4}))
if n >= 5:                                 # 5 s apart: 99 banks still fit one 600 s slot
    NAMED.append((f"All {n} banks report (S13)", OUTSIDE[4],
                  [(b, 5 * i, MOS[i % len(MOS)], False) for i, b in enumerate(IDS)], {"reports": n}))
NAMED_ROWS = Counter(b for _, _, rs, _ in NAMED for b, *_ in rs)


# --- bulk plan: multi-reporter blocks scaled to N, then each bank's remainder ------------
def seeded(rows):
    return random.Random(MAPPING_BYTES + b"|rows_per_bank=%d" % rows)


def holder_bic(holder, j, rng):
    return rng.choice(BICS[holder]) if holder else OUTSIDE[j % len(OUTSIDE)]


def thirds(x):                             # a multiple of 3 (priority thirds), at least 3
    return max(3, round(x / 3) * 3)


def multi(rows, rng):
    """Multi-reporter accounts: [(kind, bic, reporters, priorities or None, tied)]."""
    out = []
    for a, b in combinations(IDS, 2):      # every pair, ~20 % of each bank's rows
        nonrep = [o for o in IDS if o not in (a, b)]
        for j in range(math.ceil(0.20 * rows / (n - 1))):
            holder = (a, b, nonrep[(j // 4) % len(nonrep)], None)[j % 4]
            out.append(("pair", holder_bic(holder, j, rng), [a, b], None, j % 10 == 0))
    for k in range(3, n + 1):              # k = 3: ~6 % of each bank's rows; k >= 4: above the cap
        count = thirds(0.06 * rows * n / 3 if k == 3 else 0.006 * rows)
        combos = list(combinations(IDS, 3)) if k == 3 and math.comb(n, 3) <= count else None
        for j in range(count):
            reps = list(combos[j % len(combos)]) if combos else sorted(rng.sample(IDS, k), key=IDS.index)
            holder = None if j % 4 == 3 else reps[j % k]
            prio = ([i == (j // 3) % k for i in range(k)], [False] * k, [True] * k)[j % 3]
            kind = f"k{k}_" + ("one_true", "all_false", "all_true")[j % 3]
            out.append((kind, holder_bic(holder, j, rng), reps, prio, j % 10 == 0))
    return out


def remainders(rows, plan):
    used = Counter(NAMED_ROWS)
    for _, _, reps, _, _ in plan:
        used.update(reps)
    return {b: rows - used[b] for b in IDS}


rng = seeded(N)
bulk = multi(N, rng)
REM = remainders(N, bulk)
if min(REM.values()) < 3:                  # each bank needs one own, one cross, one outside row
    ok = next(m for m in itertools.count(N + 1) if min(remainders(m, multi(m, seeded(m))).values()) >= 3)
    fail(f"--rows-per-bank {N} is too small for {n} banks (the multi-reporter and named accounts "
         f"alone fill a bank's file); use at least {ok}")
for b in IDS:                              # single reporter: the remainder, split 75 / 10 / 15 %
    others = [o for o in IDS if o != b]
    cross, outside = max(1, REM[b] // 10), max(1, REM[b] * 15 // 100)
    bulk += [("own", rng.choice(BICS[b]), [b], None, False) for _ in range(REM[b] - cross - outside)]
    bulk += [("cross", rng.choice(BICS[others[i % len(others)]]), [b], None, False) for i in range(cross)]
    bulk += [("outside", OUTSIDE[i % len(OUTSIDE)], [b], None, False) for i in range(outside)]

natural_rows = sum(len(reps) for *_, reps, _, tied in bulk if not tied)
tied_accts = sum(tied for *_, tied in bulk)
if natural_rows > T_NATURAL[1] - T_NATURAL[0] or tied_accts > T_TIED[1] - T_TIED[0]:
    fail(f"{n} banks x {N} rows needs {natural_rows:,} distinct times and {tied_accts:,} tie slots; the "
         f"week holds {T_NATURAL[1] - T_NATURAL[0]:,} and {T_TIED[1] - T_TIED[0]:,}. Lower --rows-per-bank, "
         f"use fewer banks, or widen T_NATURAL / T_TIED in generate.py")

stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", os.path.splitext(os.path.basename(args.mapping))[0])
OUT = os.path.abspath(args.out or os.path.join(
    HERE, "generated_datasets", f"{time.strftime('%Y%m%d-%H%M%S')}_n{n}_r{N}_{stem}"))
if os.path.exists(OUT):
    fail(f"{OUT} already exists - every run writes a new folder")

# --- times, MOs and priorities --------------------------------------------------------
natural = iter(rng.sample(range(*T_NATURAL), natural_rows))
tie_slot = iter(range(*T_TIED))
accounts = {}       # account number -> {"bic", "kind", "label", "rows": [{bank, time, mo, priority}]}


def put(k, bic, kind, label, rows):
    a = f"{bic}66{n:02d}{k:010d}"
    assert a not in accounts
    accounts[a] = {"bic": bic, "kind": kind, "label": label, "rows": rows}
    return a


def mo_for():
    return ";".join(rng.sample(MOS, rng.choice((1, 1, 1, 2, 3))))


named_accts = [put(i, bic, "named", label, [
    {"bank": b, "time": T_NAMED + 600 * i + dt, "mo": mo, "priority": p} for b, dt, mo, p in rs])
    for i, (label, bic, rs, _) in enumerate(NAMED, 1)]
for k, (kind, bic, reps, prio, tied) in enumerate(bulk, 1001):
    t = next(tie_slot) if tied else None
    put(k, bic, kind, kind, [{"bank": b, "time": t or next(natural), "mo": mo_for(),
                              "priority": prio[i] if prio else rng.random() < 0.1}
                             for i, b in enumerate(reps)])


# --- aggregate (UC1 rules: see the dataset README) -----------------------------------------
def aggregate(rows):
    best = {}
    for r in rows:      # per-bank dedup: the earliest row wins in full (no-op: no repeats here)
        if r["bank"] not in best or r["time"] < best[r["bank"]]["time"]:
            best[r["bank"]] = r
    reps = sorted(best.values(), key=lambda r: (r["time"], NAME[r["bank"]]))
    return {"reports": reps, "first_reported": reps[0]["time"],
            "priority": any(r["priority"] for r in reps),
            "mo_union": sorted({m.strip() for r in reps for m in r["mo"].split(";")})}


agg = {a: aggregate(v["rows"]) for a, v in accounts.items()}
FAN = max(len(g["reports"]) for g in agg.values())
YN = {True: "Yes", False: "No"}
HDR = ["Account Number", "Holding Bank BIC", "Number of Reports", "Priority Processing"]
for i in range(1, FAN + 1):
    HDR += [f"Report {i} Reporting Bank", f"Report {i} Time",
            f"Report {i} Modus Operandi", f"Report {i} Priority Processing"]
export = []
for a in sorted(agg, key=lambda a: (-agg[a]["first_reported"], a)):
    g = agg[a]
    row = [a, accounts[a]["bic"], len(g["reports"]), YN[g["priority"]]]   # BIC exactly as submitted
    for r in g["reports"]:
        row += [NAME[r["bank"]], r["time"], r["mo"], YN[r["priority"]]]
    export.append([str(x) for x in row] + [""] * (len(HDR) - len(row)))


# --- write ----------------------------------------------------------------------------------
def write_csv(rel, header, rows):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def read_csv(rel):
    with open(os.path.join(OUT, rel), encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def write_all():
    os.makedirs(OUT)
    shutil.copyfile(args.mapping, os.path.join(OUT, "bank_bic_mapping_latest.csv"))
    for b in IDS:
        rows = [[a, v["bic"], r["time"], r["mo"], str(r["priority"]).upper() if b == UPPER else str(r["priority"])]
                for a, v in accounts.items() for r in v["rows"] if r["bank"] == b]
        write_csv(f"data/{b}.csv", ["Account Number", "BIC", "Time Added", "Modi Operandi",
                                    "Priority Processing"], sorted(rows))
    write_csv("expected_results/fraud_accounts_export.csv", HDR, export)


# --- self-check (reads the written files back from disk) ----------------------------------
def check():
    assert sorted(os.listdir(os.path.join(OUT, "data"))) == sorted(f"{b}.csv" for b in IDS)
    disk, bic_of, seen, per_bank = defaultdict(list), defaultdict(set), Counter(), Counter()
    for b in IDS:
        hdr, *rows = read_csv(f"data/{b}.csv")
        for a, bic, t, mo, p in rows:
            assert BIC8_RE.fullmatch(bic) and (bic in MAPPED or bic in OUTSIDE), bic
            assert len(a) == 22 and a.startswith(bic), a
            assert MO_RE.match(mo) and not mo.startswith('"'), mo
            assert p in (("TRUE", "FALSE") if b == UPPER else ("True", "False")), (b, p)
            seen[b, a] += 1
            per_bank[b] += 1
            bic_of[a].add(bic)
            disk[a].append({"bank": b, "time": int(t), "mo": mo, "priority": p.lower() == "true"})
    assert all(per_bank[b] == N for b in IDS), per_bank
    assert max(seen.values()) == 1, "a bank lists an account twice"
    assert all(len(s) == 1 for s in bic_of.values()), "an account has two BICs"
    assert disk.keys() == accounts.keys()
    for a, rows in disk.items():           # own reports only: a file holds exactly its planned rows
        assert sorted(r["bank"] for r in rows) == sorted(r["bank"] for r in accounts[a]["rows"])
    assert {a: aggregate(rs) for a, rs in disk.items()} == agg
    assert agg == {a: aggregate(rs + rs) for a, rs in disk.items()}, "not idempotent"
    assert read_csv("expected_results/fraud_accounts_export.csv") == [HDR] + export
    with open(os.path.join(OUT, "bank_bic_mapping_latest.csv"), "rb") as f:
        assert f.read() == MAPPING_BYTES

    for g in agg.values():
        assert 1 <= len(g["reports"]) <= FAN
        assert len(g["reports"]) == len({r["bank"] for r in g["reports"]})
    for a, v in accounts.items():
        ps = [r["priority"] for r in agg[a]["reports"]]
        if v["kind"].endswith("_one_true"):
            assert sum(ps) == 1 and agg[a]["priority"] is True
        elif v["kind"].endswith("_all_false"):
            assert not any(ps) and agg[a]["priority"] is False
        elif v["kind"].endswith("_all_true"):
            assert all(ps) and agg[a]["priority"] is True
    for a, (_, bic, _, exp) in zip(named_accts, NAMED):
        g = agg[a]
        assert accounts[a]["bic"] == bic
        assert len(g["reports"]) == exp["reports"], a
        assert exp.get("priority", g["priority"]) == g["priority"], a
        assert exp.get("mo_union", g["mo_union"]) == g["mo_union"], a
        assert exp.get("banks", [r["bank"] for r in g["reports"]]) == [r["bank"] for r in g["reports"]], a
    pairs = {frozenset(r["bank"] for r in v["rows"]) for v in accounts.values() if v["kind"] == "pair"}
    assert pairs == {frozenset(p) for p in combinations(IDS, 2)}, "a pair of banks never corroborates"
    fan = Counter(len(g["reports"]) for g in agg.values())
    assert set(fan) == set(range(1, n + 1)), fan

    kinds = Counter(v["kind"] for v in accounts.values())
    return dict(
        banks=n, rows_per_bank=N, rows=sum(per_bank.values()), accounts=len(agg),
        fan_in=dict(sorted(fan.items())), blocks=dict(kinds),
        held_outside=sum(v["bic"] in OUTSIDE for v in accounts.values()),
        priority_yes=sum(g["priority"] for g in agg.values()),
        tied=sum(len(g["reports"]) > 1 and len({r["time"] for r in g["reports"]}) == 1 for g in agg.values()),
        multi_mo=sum(len(g["mo_union"]) > 1 for g in agg.values()),
        mo_union_collapsed=sum(len(g["reports"]) > 1 and len(g["mo_union"]) < len(g["reports"])
                               for g in agg.values()),
        comma_mo_rows=sum("," in r["mo"] for v in accounts.values() for r in v["rows"]),
        distinct_bics_used=len({v["bic"] for v in accounts.values()}),
    )


# --- dataset README ---------------------------------------------------------------------------
def table(header, rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def readme(c):
    def block(label, pred, what):          # [label, accounts, rows, what] for the kinds pred accepts
        vs = [v for v in accounts.values() if pred(v["kind"])]
        return [label, f"{len(vs):,}", f"{sum(len(v['rows']) for v in vs):,}", what]

    blocks = [
        block("Named scenario accounts", lambda k: k == "named", "the fixed scenarios in the next table"),
        block("2-bank corroboration", lambda k: k == "pair",
              f"every one of the {math.comb(n, 2)} pairs of banks, {math.ceil(0.20 * N / (n - 1))} accounts "
              "each; the holding BIC rotates: first reporter, second reporter, a bank that did not report, outside"),
        block("3-bank corroboration", lambda k: k.startswith("k3_"),
              "exactly 3 reporters, the BUG-005 boundary; priority in thirds: one True (OR gives Yes), "
              "all False (No), all True (Yes)"),
    ]
    if n >= 4:
        blocks.append(block(f"4- to {n}-bank corroboration",
                            lambda k: k.startswith("k") and not k.startswith("k3_"),
                            f"{thirds(0.006 * N)} accounts for each reporter count from 4 to {n}, reporters "
                            "drawn at random; above the BUG-005 cap of 3; same priority thirds"))
    blocks += [
        block("Own account, single reporter", lambda k: k == "own",
              "a bank reports an account held at one of its own BICs"),
        block("Held at another participating bank", lambda k: k == "cross",
              "a bank reports an account held at another bank's BIC; the holding bank does not report it"),
        block("Held outside the participating banks", lambda k: k == "outside",
              "the holding BIC is not in the mapping"),
    ]
    named = [[i, f"`{a}`", accounts[a]["label"], accounts[a]["bic"], len(agg[a]["reports"]),
              ", ".join(r["bank"] for r in agg[a]["reports"]), YN[agg[a]["priority"]],
              "; ".join(agg[a]["mo_union"])] for i, a in enumerate(named_accts, 1)]
    bug005 = ("" if FAN <= 3 else
              f"\n**More than 3 reporters (BUG-005).** Accounts here have up to {FAN} reports. Production "
              "`uc1_matching_script.py` computes `reporting_bank_count` as `min(number_of_reports, 3)`, a known "
              "bug. These expected results are deliberately **uncapped**: they show the correct target "
              "behaviour.\n")
    with open(os.path.join(HERE, "templates", "dataset_README.md"), encoding="utf-8") as f:
        text = string.Template(f.read()).substitute(
            n=n, n2=f"{n:02d}", rows_per_bank=f"{N:,}", rows_per_bank_raw=N, rows=f"{c['rows']:,}",
            accounts=f"{c['accounts']:,}", fan=FAN, upper=UPPER, mo_count=len(MOS),
            bank_list=", ".join(f"`{b}`" for b in IDS),
            banks_table=table(["#", "Bank ID", "Display name", "BICs in the mapping", "Rows"],
                              [[i, f"`{b}`", NAME[b], len(BICS[b]), f"{N:,}"] for i, b in enumerate(IDS, 1)]),
            outside_list=", ".join(f"`{b}`" for b in OUTSIDE),
            mo_list="\n".join(f"- `{m}`" for m in MOS),
            size_table=table(["", ""], [
                ["Rows", f"{c['rows']:,} ({N:,} in each of the {n} bank files)"],
                ["Accounts on the shared list", f"{c['accounts']:,}"],
                ["Held at a BIC in the mapping / outside it",
                 f"{c['accounts'] - c['held_outside']:,} / {c['held_outside']:,}"],
                ["Accounts with Priority Processing = Yes", f"{c['priority_yes']:,}"],
                ["Accounts with more than one distinct MO", f"{c['multi_mo']:,}"],
                ["Multi-reporter accounts whose MO union is smaller than their report count",
                 f"{c['mo_union_collapsed']:,}"],
                ["Rows whose MO contains a comma", f"{c['comma_mo_rows']:,}"],
                ["Multi-reporter accounts with tied timestamps", f"{c['tied']:,}"],
                ["Distinct holding BICs used", f"{c['distinct_bics_used']:,}"],
            ]),
            fan_table=table(["Reports", "Accounts"], [[k, f"{v:,}"] for k, v in c["fan_in"].items()]),
            block_table=table(["Block", "Accounts", "Rows", "What it exercises"], blocks),
            named_table=table(["#", "Account", "Scenario", "Holding Bank BIC", "Reports",
                               "Reporting banks", "Priority", "MO union"], named),
            bug005=bug005, t_tied=T_TIED[0], t0=T0,
        )
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


try:
    write_all()
    counters = check()
    readme(counters)
except BaseException:
    shutil.rmtree(OUT, ignore_errors=True)  # never leave a half-written or unchecked dataset behind
    raise
for key, val in counters.items():
    print(f"{key:20s} {val}")
print(f"\nwrote {OUT}")
