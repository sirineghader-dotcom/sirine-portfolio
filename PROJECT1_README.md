# Project 1: Marketing Performance Dashboard

**Live dashboard:** https://sirineghader-dotcom.github.io/sirine-portfolio/marketing-dashboard.html

A standalone web dashboard that an agency owner can open on Monday morning to see which lead
sources are worth next month's budget. It is built from the agency's GoHighLevel (GHL) data,
pulled through the GHL API, and compares every source side by side. There are no blended totals.

Built with the GoHighLevel API and Claude Code.

---

## What the owner sees

The page reads top to bottom in the order the brief asks for: **volume → pipeline → conversion → revenue**.

| # | Section | Chart | What it answers |
|---|---------|-------|-----------------|
| 1 | The short answer | Three lists: Spend more / Keep steady / Spend less | Where to put next month's budget, in plain English |
| 2 | Volume | Bar chart, sorted | How many real, unique leads each source brought in |
| 3 | Pipeline | Stacked bar (count or share) | Where each source's deals sit across the 8 pipeline stages |
| 4 | Conversion | One funnel per source | How many leads make it from each step to the next |
| 5 | Revenue | Bar chart, sorted highest first | Closed revenue from each source |
| 6 | Behind the numbers | Table | How many records were removed or adjusted, and why |

Every chart has a **View data table** with the exact numbers. The page works on phones and in
light or dark mode.

### The budget recommendation

There is no ad spend data, so sources are ranked by **closed revenue per lead**. This combines
volume, conversion and revenue: it is what one more lead from that source has been worth so far.

| Source | Leads | Deals | Won | Closed revenue | Revenue per lead | Advice |
|---|---:|---:|---:|---:|---:|---|
| Instagram Ad | 29 | 22 | 5 | $31,500 | $1,086 | Spend more |
| Billboard | 37 | 24 | 4 | $40,000 | $1,081 | Spend more |
| Webinar | 33 | 22 | 4 | $33,000 | $1,000 | Spend more |
| LinkedIn Outreach | 22 | 16 | 2 | $20,000 | $909 | Keep steady |
| Cold Email | 27 | 22 | 2 | $13,500 | $500 | Keep steady |
| Google Search | 34 | 21 | 4 | $15,500 | $456 | Keep steady |
| Referral | 46 | 30 | 3 | $19,250 | $418 | Spend less |
| Website Form | 29 | 23 | 1 | $11,000 | $379 | Spend less |
| Facebook Ad | 37 | 24 | 3 | $7,000 | $189 | Spend less |

The dashboard also tells the owner two things:
- Each source has only 1–5 closed sales, so budget should shift in steps (about 10–20% a month).
- Referral and Website Form aren't ads you buy. For those two, "spend" means effort, such as
  referral rewards or improving the form page.

---

## Which records belong to this agency

The GHL sandbox is shared by every student, so most of what the API returns is not this agency's.
The account holds 414 contacts, 278 deals and 20 pipelines. This agency's records are:

- **Contacts** tagged `dash-project` (321 before cleaning), and
- **Deals** in the 8-stage **Sales Pipeline** (`a5UYvGBOnvtiBm0W6H8D`) attached to those contacts.

Everything else belongs to other students or to GHL's demo data (tagged `demo-data` / `sandbox`).
The pipeline is matched by its ID rather than its name, so a pipeline another student creates
with the same name can't be picked up by mistake.

---

## Data cleaning

Every rule runs on each rebuild, and the dashboard shows the owner the same table.

### Removed from every chart

| Rule | Removed | Why |
|---|---:|---|
| Other businesses' records | 93 contacts | Not tagged `dash-project`: other students' or demo records in the shared account. |
| Other businesses' deals | 74 deals | Deals belonging to those other contacts and pipelines. |
| Internal and test leads | 15 contacts | Tagged `internal`, or named like a test (test, demo, fake). These are the team filling in its own forms, not prospects. All 15 came in as "Website Form", so keeping them would inflate that source. |
| Duplicate contacts | 12 contacts | The same person entered twice: same name and company, with a `.2` copy of their email (for example `name.123.2@example.com`), usually under a different source. One was already tagged `dq - duplicate`. The first entry is kept, so each person counts once and is credited to the source that brought them in first. The first entry is also the one holding the deal. |
| Leads with no source | 0 | Checked. They couldn't be credited to any channel. |
| Deals in another pipeline | 0 | Checked. Only the 8-stage Sales Pipeline is reported. |
| Deals without a valid lead | 0 | Checked. Deals attached to no contact, or to a removed one. |
| Second deal for the same lead | 0 | Checked. Each lead counts once in the pipeline. |
| Deals with impossible dates | 0 | Checked. Created in the future, or moved stage before being created. |

### Kept, but handled with care

| Rule | Count | How it's handled |
|---|---:|---|
| Won deals with a $0 value | 1 | Counted as a won deal; left out of revenue because the real amount is unknown. |
| Won deals with an unrealistic value | 2 | Recorded at $145,000, more than 5× the typical deal of $7,250, so almost certainly a typo. Counted as won deals; left out of revenue. Including them would have added $290,000 and made Facebook Ad and Instagram Ad look like the best sources. |
| Open or lost deals with odd values | 12 | 8 at $0 and 4 at $145,000. They don't affect closed revenue, so they stay in the pipeline counts. |
| Disqualified deals still marked "open" | 2 | The stage was updated but the status wasn't. Counted by stage, as Disqualified. |
| Source spellings merged | 0 | Checked. Spelling variants (capitals, spaces, plurals) would be merged under one name. |
| Deals marked "won" outside the Closed stage | 0 | Checked. Only the Closed stage counts as won. |

**After cleaning:** 294 leads and 204 deals across 9 sources.

### Other things noticed

- Every record was created between 1 and 4 September 2026 (the data was seeded at once), so
  there is no real month-by-month history. The dashboard compares sources over the whole period
  and doesn't show trends.

---

## How the numbers are calculated

- **Lead volume:** cleaned contacts, grouped by the source recorded when they first came in.
- **Pipeline:** each deal counted once, in the stage it sits in today. Each source's stage
  counts add up to its total deals.
- **Stage-to-stage conversion:** the 8 stages aren't a straight line (Disqualified, No Show,
  Cancelled and Lost are exits), so each deal's current stage tells us how far it got:

  | Funnel step | Counts deals currently in |
  |---|---|
  | Leads | All cleaned contacts from that source |
  | Entered the pipeline | Any of the 8 stages |
  | Qualified | Any stage except Disqualified |
  | Booked a call | Booked call, No Show, Cancelled, Follow Up, Lost, Closed |
  | Attended the call | Follow Up, Lost, Closed |
  | Won | Closed |

  Each funnel shows the count at each step and the percentage that moved on from the step before.
- **Closed revenue:** the sum of deal values in the Closed stage, excluding the 3 suspicious
  values above.

### Consistency checks

`scripts/build_data.py` refuses to write the data file (it exits with an error) unless:
- each source's stage counts add up to its total deals,
- no source has more deals than leads,
- no funnel step is larger than the step before it,
- each source's won count equals its Closed stage count, and
- source totals add up to the number of cleaned leads and deals.

The figures were also recomputed independently from the raw API data, and every source's
leads, deals, stage counts, wins and revenue matched.

---

## Tech stack and hosting

| Part | Choice |
|---|---|
| Data pull, cleaning and aggregation | Python 3 standard library only (`scripts/build_data.py`) |
| Data file | `data/dashboard-data.json`: aggregates only, no names, emails or phone numbers |
| Dashboard | A single static page (`marketing-dashboard.html`), using [Chart.js](https://www.chartjs.org/) for the bar charts and plain HTML/CSS for the funnels |
| Hosting | GitHub Pages |
| Refresh | Scheduled snapshot. The page shows the date the data was pulled. A daily GitHub Action (`.github/workflows/refresh-dashboard.yml`) is included, but GitHub has not registered it on this account yet, so refreshes are currently run by hand. |

The API key never reaches the browser: the page only reads the cleaned summary file.

---

## How to run it

```bash
# 1. Pull, clean and aggregate (writes data/dashboard-data.json)
GHL_API_KEY=your-key GHL_LOCATION_ID=yLiKZKvk2CeI2ckIqd1L python3 scripts/build_data.py

# 2. View the dashboard locally
python3 -m http.server 8000
# then open http://localhost:8000/marketing-dashboard.html
```

The script prints each cleaning rule with its count, and fails if any consistency check fails.

## Files

| File | Purpose |
|---|---|
| `marketing-dashboard.html` | The dashboard page |
| `scripts/build_data.py` | Pulls from the GHL API, cleans, aggregates and checks the data |
| `data/dashboard-data.json` | The cleaned, aggregated data the page reads |
| `.github/workflows/refresh-dashboard.yml` | Daily refresh job (not yet running, see above) |
| `PROJECT1_BRIEF.md` | Working notes: requirements, data findings and plan |
