"""Build data/dashboard-data.json for marketing-dashboard.html.

Pulls contacts, opportunities and pipelines from the GoHighLevel API, removes
records that don't belong in the numbers (each removal is counted and explained),
aggregates everything by lead source and writes aggregates only - no names,
emails or phone numbers leave this script.

Run:  GHL_API_KEY=... GHL_LOCATION_ID=... python3 scripts/build_data.py
Fails (exit 1) if any stage breakdown doesn't add up to its total.
"""
import json
import os
import re
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

API = "https://services.leadconnectorhq.com"
LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "yLiKZKvk2CeI2ckIqd1L")
API_KEY = os.environ.get("GHL_API_KEY", "")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "dashboard-data.json")

# Which records are this agency's: everything it imported carries this tag.
# Other students share the sandbox and use their own tags/pipelines.
AGENCY_TAG = "dash-project"
PIPELINE_NAME = "Sales Pipeline"
INTERNAL_TAGS = {"internal"}

# The 8 pipeline stages, in the order a deal moves through them.
STAGE_ORDER = ["Qualified Opt In", "Booked call", "Follow Up", "Closed",
               "No Show", "Cancelled", "Lost", "Disqualified"]
# Funnel steps: which current stages mean a lead has *reached* each step.
FUNNEL = [
    ("Leads", None),
    ("Entered the pipeline", set(STAGE_ORDER)),
    ("Qualified", set(STAGE_ORDER) - {"Disqualified"}),
    ("Booked a call", {"Booked call", "Follow Up", "Closed", "No Show", "Cancelled", "Lost"}),
    ("Attended the call", {"Follow Up", "Closed", "Lost"}),
    ("Won", {"Closed"}),
]
# A deal value more than this many times the typical (median) deal is treated as a typo.
OUTLIER_FACTOR = 5


def request(method, path, body=None):
    headers = {"Version": "2021-07-28", "Accept": "application/json",
               "User-Agent": "marketing-dashboard-build/1.0"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch():
    pipelines = request("GET", f"/opportunities/pipelines?locationId={LOCATION_ID}")["pipelines"]
    opps, page = [], 1
    while True:
        batch = request("GET", f"/opportunities/search?location_id={LOCATION_ID}&limit=100&page={page}")
        opps += batch.get("opportunities", [])
        if len(batch.get("opportunities", [])) < 100:
            break
        page += 1
    contacts, after = [], None
    while True:
        body = {"locationId": LOCATION_ID, "pageLimit": 500}
        if after:
            body["searchAfter"] = after
        batch = request("POST", "/contacts/search", body).get("contacts", [])
        contacts += batch
        if len(batch) < 500:
            break
        after = batch[-1]["searchAfter"]
    return pipelines, opps, contacts


def norm_email(email):
    """Lowercase, drop +aliases and numbered copies (jane.doe.2@ -> jane.doe@)."""
    if not email or "@" not in email:
        return None
    local, domain = email.strip().lower().split("@", 1)
    local = re.sub(r"\+.*$", "", local)
    local = re.sub(r"\.\d+$", "", local)
    return f"{local}@{domain}"


def norm_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    return digits[-9:] if len(digits) >= 7 else None


def source_key(source):
    """Spelling-insensitive key: 'facebook ads ', 'Facebook-Ad' -> 'facebookad'."""
    key = re.sub(r"[^a-z0-9]", "", (source or "").lower())
    return re.sub(r"s$", "", key) or None


def parse_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def build(pipelines, opps, contacts, now):
    pipeline = next(p for p in pipelines if p["name"] == PIPELINE_NAME)
    stage_name = {s["id"]: s["name"] for s in pipeline["stages"]}
    assert sorted(stage_name.values()) == sorted(STAGE_ORDER), "pipeline stages changed in GHL"

    removed = []  # (rule, what, count, reason)

    # 1. Keep only this agency's records.
    ours = [c for c in contacts if AGENCY_TAG in (c.get("tags") or [])]
    removed.append(("Other businesses' records", "contacts", len(contacts) - len(ours),
                    f"The GoHighLevel account is shared with other businesses. Only leads tagged "
                    f"“{AGENCY_TAG}” belong to this agency."))

    # 2. Internal / test leads.
    def is_test(c):
        text = " ".join(str(c.get(k) or "") for k in ("contactName", "email", "companyName")).lower()
        return bool(INTERNAL_TAGS & set(c.get("tags") or [])) or bool(
            re.search(r"\btest\b|\bdemo\b|\bfake\b|\bdummy\b|asdf", text))
    tests = [c for c in ours if is_test(c)]
    ours = [c for c in ours if not is_test(c)]
    removed.append(("Internal and test leads", "contacts", len(tests),
                    "Tagged “internal” or named like a test (test, demo, fake). These are the team "
                    "filling in its own forms, not real prospects."))

    # 3. Duplicate contacts: same person entered twice. Keep the first entry (first touch).
    ours.sort(key=lambda c: c.get("dateAdded") or "")
    seen, kept, dupes = {}, [], []
    for c in ours:
        keys = {k for k in (
            ("email", norm_email(c.get("email"))),
            ("phone", norm_phone(c.get("phone"))),
            ("name", (c.get("contactName") or "").strip().lower(), (c.get("companyName") or "").strip().lower()),
        ) if all(k[1:]) }
        if keys & seen.keys():
            dupes.append(c)
            continue
        for k in keys:
            seen[k] = c["id"]
        kept.append(c)
    ours = kept
    removed.append(("Duplicate contacts", "contacts", len(dupes),
                    "The same person (same name and company, or same email/phone) was entered twice, "
                    "usually with a different source. Kept the first entry so each person counts once, "
                    "credited to the source that brought them in first."))

    # 4. Missing source; merge spelling variants into the most common spelling.
    spellings = defaultdict(Counter)
    for c in ours:
        if source_key(c.get("source")):
            spellings[source_key(c.get("source"))][c["source"].strip()] += 1
    canonical = {k: v.most_common(1)[0][0] for k, v in spellings.items()}
    respelled = 0
    for c in ours:
        key = source_key(c.get("source"))
        c["_source"] = canonical.get(key)
        respelled += bool(key) and c["source"].strip() != c["_source"]
    no_source = [c for c in ours if not c["_source"]]
    ours = [c for c in ours if c["_source"]]
    removed.append(("Leads with no source", "contacts", len(no_source),
                    "Can’t be credited to any channel, so they can’t inform the budget."))

    contact_by_id = {c["id"]: c for c in ours}
    spelling_note = ("Source spellings merged", "info", respelled,
                     "The same channel typed differently (capitals, spaces, plural) is combined "
                     "under one name. No lead is removed.")

    # Opportunities: only this agency's sales pipeline, attached to a kept contact.
    our_opps = [o for o in opps if AGENCY_TAG in ((o.get("contact") or {}).get("tags") or [])]
    removed.append(("Other businesses' deals", "deals", len(opps) - len(our_opps),
                    "Deals belonging to other businesses in the shared account."))
    wrong_pipe = [o for o in our_opps if o["pipelineId"] != pipeline["id"]]
    our_opps = [o for o in our_opps if o["pipelineId"] == pipeline["id"]]
    removed.append(("Deals in another pipeline", "deals", len(wrong_pipe),
                    f"Only the 8-stage “{PIPELINE_NAME}” is reported."))
    orphan = [o for o in our_opps if o.get("contactId") not in contact_by_id]
    our_opps = [o for o in our_opps if o.get("contactId") in contact_by_id]
    removed.append(("Deals without a valid lead", "deals", len(orphan),
                    "Attached to no contact, or to a contact removed above (internal, duplicate, no source)."))

    # Keep one deal per contact (the earliest one).
    by_contact = {}
    for o in sorted(our_opps, key=lambda o: o.get("createdAt") or ""):
        o["_stage"] = stage_name[o["pipelineStageId"]]
        by_contact.setdefault(o["contactId"], o)
    extra = len(our_opps) - len(by_contact)
    our_opps = list(by_contact.values())
    removed.append(("Second deal for the same lead", "deals", extra,
                    "One lead is counted once in the pipeline."))

    # Impossible dates.
    def bad_dates(o):
        created, changed = parse_date(o.get("createdAt")), parse_date(o.get("lastStageChangeAt"))
        return (created and created > now) or (created and changed and changed < created)
    dated = [o for o in our_opps if bad_dates(o)]
    our_opps = [o for o in our_opps if not bad_dates(o)]
    removed.append(("Deals with impossible dates", "deals", len(dated),
                    "Created in the future, or moved to a stage before they were created."))

    # Deal values: counted in the pipeline, but suspicious values are kept out of revenue.
    positive = [o["monetaryValue"] for o in our_opps if (o.get("monetaryValue") or 0) > 0]
    typical = statistics.median(positive) if positive else 0
    limit = typical * OUTLIER_FACTOR

    def value_issue(o):
        v = o.get("monetaryValue")
        if v is None or v <= 0:
            return "zero"
        if v > limit:
            return "outlier"
        return None

    won = [o for o in our_opps if o["_stage"] == "Closed"]
    won_zero = [o for o in won if value_issue(o) == "zero"]
    won_outlier = [o for o in won if value_issue(o) == "outlier"]
    other_flagged = Counter(value_issue(o) for o in our_opps if o["_stage"] != "Closed" and value_issue(o))
    value_notes = [
        spelling_note,
        ("Won deals with a $0 value", "revenue", len(won_zero),
         "Marked won but no price was entered. Counted as a won deal; left out of revenue "
         "because the real amount is unknown."),
        ("Won deals with an unrealistic value", "revenue", len(won_outlier),
         f"Recorded at {fmt_money(won_outlier[0]['monetaryValue']) if won_outlier else 'a value'}, more than "
         f"{OUTLIER_FACTOR}× the typical deal of {fmt_money(typical)} — almost certainly a typo. "
         "Counted as a won deal; left out of revenue."),
        ("Open or lost deals with odd values", "info",
         other_flagged["zero"] + other_flagged["outlier"],
         f"{other_flagged['zero']} at $0 and {other_flagged['outlier']} at an unrealistic amount. "
         "They don’t affect closed revenue, so they stay in the pipeline counts."),
    ]
    status_mismatch = sum(1 for o in our_opps if o["_stage"] == "Disqualified" and o.get("status") == "open")
    value_notes.append(("Disqualified deals still marked “open”", "info", status_mismatch,
                        "The stage says Disqualified but the status was never updated. "
                        "They are counted as Disqualified."))
    won_not_closed = sum(1 for o in our_opps if o.get("status") == "won" and o["_stage"] != "Closed")
    value_notes.append(("Deals marked “won” outside the Closed stage", "info", won_not_closed,
                        "Counted in the stage they sit in; only the Closed stage counts as won."))

    # ---- Aggregate by source ----
    sources = sorted({c["_source"] for c in ours})
    leads = Counter(c["_source"] for c in ours)
    stages = {s: Counter() for s in sources}
    revenue = Counter()
    won_count = Counter()
    won_valued = Counter()
    funnel = {s: [0] * len(FUNNEL) for s in sources}
    for s in sources:
        funnel[s][0] = leads[s]
    for o in our_opps:
        src = contact_by_id[o["contactId"]]["_source"]
        stages[src][o["_stage"]] += 1
        for i, (_, reached) in enumerate(FUNNEL[1:], start=1):
            if o["_stage"] in reached:
                funnel[src][i] += 1
        if o["_stage"] == "Closed":
            won_count[src] += 1
            if not value_issue(o):
                revenue[src] += o["monetaryValue"]
                won_valued[src] += 1

    # Consistency checks: every breakdown must add up to its total.
    errors = []
    for s in sources:
        deals = sum(stages[s].values())
        if deals != funnel[s][1]:
            errors.append(f"{s}: stages sum to {deals}, pipeline total is {funnel[s][1]}")
        if funnel[s][1] > leads[s]:
            errors.append(f"{s}: more deals than leads")
        if any(funnel[s][i] < funnel[s][i + 1] for i in range(len(FUNNEL) - 1)):
            errors.append(f"{s}: funnel grows at some step {funnel[s]}")
        if won_count[s] != stages[s]["Closed"]:
            errors.append(f"{s}: won count != Closed stage")
    if sum(leads.values()) != len(ours):
        errors.append("lead counts don't sum to kept contacts")
    if sum(sum(v.values()) for v in stages.values()) != len(our_opps):
        errors.append("stage counts don't sum to kept deals")
    if errors:
        sys.exit("Consistency check failed:\n  " + "\n  ".join(errors))

    rows = []
    for s in sources:
        rows.append({
            "source": s,
            "leads": leads[s],
            "deals": funnel[s][1],
            "stages": {st: stages[s][st] for st in STAGE_ORDER},
            "funnel": funnel[s],
            "won": won_count[s],
            "wonWithValue": won_valued[s],
            "revenue": revenue[s],
        })

    return {
        "generatedAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pipeline": PIPELINE_NAME,
        "stageOrder": STAGE_ORDER,
        "funnelSteps": [name for name, _ in FUNNEL],
        "sources": rows,
        "typicalDeal": typical,
        "cleaning": {
            "rawContacts": len(contacts),
            "rawDeals": len(opps),
            "keptContacts": len(ours),
            "keptDeals": len(our_opps),
            "removed": [dict(zip(("rule", "kind", "count", "reason"), r)) for r in removed],
            "adjusted": [dict(zip(("rule", "kind", "count", "reason"), r)) for r in value_notes],
        },
    }


def fmt_money(v):
    return f"${v:,.0f}"


def main():
    pipelines, opps, contacts = fetch()
    data = build(pipelines, opps, contacts, datetime.now(timezone.utc))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    c = data["cleaning"]
    print(f"Kept {c['keptContacts']}/{c['rawContacts']} contacts, {c['keptDeals']}/{c['rawDeals']} deals")
    for r in c["removed"] + c["adjusted"]:
        print(f"  {r['count']:>4}  {r['rule']}")


if __name__ == "__main__":
    main()
