#!/usr/bin/env python3
"""
Generates the demo dataset the hosted dashboard shows until it is pointed at
the live Dashboard API (workflow 09):

  data/ad-spend.csv        realistic daily spend sheet, per source and line item
  data/demo-leads.csv      one anonymised row per lead (same columns as the API)
  dashboard/data.js        both, bundled for the static dashboard

Seeded, so it is reproducible. Assumptions are documented inline and in README.
"""
import calendar
import csv
import json
import math
import pathlib
import random
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
rng = random.Random(20261009)
START, END = date(2026, 7, 1), date(2026, 10, 9)          # 101 days, "today" is Oct 10
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
ET = timedelta(hours=-4)                                   # agency is on US Eastern

# Per-source behaviour. Meta: cheap, high volume, weaker intent.
# Website (Google search + SEO): fewer, warmer leads. Referral: few, very warm.
SOURCES = {
    "meta":     dict(per_day=5.2, weekend=0.8, q=0.27, review=0.15, book=0.52, show=0.57,
                     book_lag=(0.2, 2.5), evening=0.45),
    "website":  dict(per_day=1.9, weekend=0.45, q=0.46, review=0.17, book=0.63, show=0.77,
                     book_lag=(0.1, 1.5), evening=0.2),
    "referral": dict(per_day=0.5, weekend=0.3, q=0.70, review=0.12, book=0.80, show=0.90,
                     book_lag=(0.05, 1.0), evening=0.15),
}


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def poisson(lam):
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def opt_in_time(d, evening_share):
    if rng.random() < evening_share:
        hour = rng.uniform(18, 23.5)
    else:
        hour = min(17.99, max(7, rng.gauss(12.5, 2.6)))
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(hours=hour) - ET


def reply_minutes():
    """Automation: webhook -> GHL -> Claude -> send. Mostly 1-2 minutes."""
    m = rng.lognormvariate(math.log(1.15), 0.35)
    if rng.random() < 0.015:            # GHL API slowness; retries kick in
        m = rng.uniform(3.5, 7.5)
    return round(m, 2)


def business_slot(after, lag_days):
    """An appointment slot on a weekday, 9:00-16:30 Eastern."""
    t = after + timedelta(days=lag_days)
    local = t + ET
    while local.weekday() >= 5:
        local += timedelta(days=1)
    local = local.replace(hour=rng.choice([9, 10, 11, 13, 14, 15, 16]),
                          minute=rng.choice([0, 30]), second=0, microsecond=0)
    return local - ET


leads = []
for d in days():
    for source, s in SOURCES.items():
        lam = s["per_day"] * (s["weekend"] if d.weekday() >= 5 else 1)
        # Meta creative fatigue in late August, refreshed in September
        if source == "meta" and date(2026, 8, 18) <= d <= date(2026, 9, 3):
            lam *= 0.78
        for _ in range(poisson(lam)):
            t = opt_in_time(d, s["evening"])
            if t > NOW:
                continue
            first = t + timedelta(minutes=reply_minutes())
            r = rng.random()
            if r < s["q"]:
                qual, score = "qualified", rng.randint(70, 97)
            elif r < s["q"] + s["review"]:
                qual, score = "needs_review", rng.randint(41, 69)
            else:
                qual, score = "not_qualified", rng.randint(6, 39)
            booked = showed = noshow = None
            if qual == "qualified" and rng.random() < s["book"]:
                lag = rng.uniform(*s["book_lag"]) * (1 if rng.random() < 0.7 else 2.5)
                booked = t + timedelta(days=lag)
                appt = business_slot(booked, rng.uniform(1, 5))
                if booked > NOW:
                    booked = None
                elif appt <= NOW:
                    if rng.random() < s["show"]:
                        showed = appt
                    else:
                        noshow = appt
            leads.append([source, t, first, qual, score, booked, showed, noshow])
leads.sort(key=lambda r: r[1])

# ---------------- spend sheet: what each source actually costs per day
spend = []
for d in days():
    dim = calendar.monthrange(d.year, d.month)[1]
    wk = d.weekday() >= 5
    meta = rng.uniform(150, 195) * (0.85 if wk else 1)
    if date(2026, 9, 4) <= d:          # new creative + budget bump after fatigue
        meta *= 1.08
    spend.append((d, "meta", "Meta Ads: lead form campaigns", meta))
    spend.append((d, "meta", "Creative production (monthly, spread daily)", 900 / dim))
    spend.append((d, "website", "Google Ads: B2B search", rng.uniform(58, 82) * (0.6 if wk else 1)))
    spend.append((d, "website", "SEO & content retainer (monthly, spread daily)", 1800 / dim))
    spend.append((d, "website", "Landing page tools (monthly, spread daily)", 149 / dim))
    spend.append((d, "referral", "Partner program: CRM seat & events (monthly, spread daily)", 450 / dim))
# Referral bonus: $200 paid to the referrer when the referred lead shows up.
for l in leads:
    if l[0] == "referral" and l[6]:
        spend.append(((l[6] + ET).date(), "referral", "Referral bonus ($200 per showed call)", 200.0))

agg = {}
for d, s, item, amt in spend:
    agg[(d, s, item)] = agg.get((d, s, item), 0) + amt
spend_rows = sorted(((d.isoformat(), s, i, round(a, 2)) for (d, s, i), a in agg.items()))

# ---------------- write files
iso = lambda x: x.strftime("%Y-%m-%dT%H:%M:%SZ") if x else ""
(ROOT / "data").mkdir(exist_ok=True)
with open(ROOT / "data" / "ad-spend.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "source", "line_item", "amount_usd"])
    w.writerows(spend_rows)
with open(ROOT / "data" / "demo-leads.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["source", "opted_in_at", "first_reply_at", "qualification", "score", "booked_at", "showed_at", "no_show_at"])
    for l in leads:
        w.writerow([l[0], iso(l[1]), iso(l[2]), l[3], l[4], iso(l[5]), iso(l[6]), iso(l[7])])

payload = {
    "generated_at": iso(NOW), "demo": True,
    "leads": [[l[0], iso(l[1]), iso(l[2]), l[3], l[4], iso(l[5]) or None, iso(l[6]) or None, iso(l[7]) or None]
              for l in leads],
    "spend": [list(r) for r in spend_rows],
}
(ROOT / "dashboard").mkdir(exist_ok=True)
(ROOT / "dashboard" / "data.js").write_text(
    "// Demo data generated by scripts/generate_demo_data.py. Same shape as the live Dashboard API.\n"
    "window.STL_DEMO_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n")

# ---------------- print a summary so the numbers can be sanity-checked
for s in SOURCES:
    L = [l for l in leads if l[0] == s]
    sp = sum(r[3] for r in spend_rows if r[1] == s)
    q = sum(l[3] == "qualified" for l in L)
    b = sum(bool(l[5]) for l in L)
    sh = sum(bool(l[6]) for l in L)
    ns = sum(bool(l[7]) for l in L)
    print(f"{s:9} leads {len(L):4} qual {q:4} booked {b:3} showed {sh:3} noshow {ns:3} spend ${sp:9,.0f} "
          f"CPL ${sp/len(L):6.0f} per booked ${sp/b:6.0f} per show ${sp/sh:6.0f} no-show {ns/(sh+ns):.0%}")
