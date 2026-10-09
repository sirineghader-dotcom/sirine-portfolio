# Project 1: Marketing Performance Dashboard — Brief & Handoff

AI Consulting Program assignment. Built with the GoHighLevel (GHL) API + Claude Code.
Work branch: `claude/ai-consulting-project-7qlcmq`.

## Requirements (from the program team)

**Background:** An agency has run paid acquisition for three months but has no consolidated
view of what's working. All data lives in GoHighLevel: leads, sources and an 8-stage Sales
Pipeline. Build a dashboard the owner can check Monday morning and instantly know where to put
next month's budget.

**Deliver:** a live, shareable link the owner opens in a browser. Standalone web dashboard,
*not* built inside GHL.

**Data:** pull it from the GHL sandbox via the API. The sandbox is shared, so it also holds
other students' records: deciding which records belong to this agency is part of the job.
There is no ad spend data; base budget advice on volume, conversion and revenue.

**Must show (all by source, never combined totals):**
- Lead volume
- Pipeline progression through the 8 stages
- Stage-to-stage conversion rates
- Closed revenue

**Segmentation rule:** no single blended numbers. Every metric lets the owner compare
Source A vs. B vs. C directly.

**Data quality (the real work):** the data is messy. Expect duplicate contacts, test/internal
leads, missing sources and suspicious deal values. Not every problem is listed. Find what's
there, decide what to exclude, justify each exclusion, and show the owner how many records
were removed and why.

**Charts:**
- Volume by source → bar chart
- Pipeline distribution → stacked bar or funnel
- Conversion rates → funnel chart
- Revenue by source → sorted bar chart
- No pie charts with many slices, no overloaded combo charts

**Consistency rule:** stage breakdowns must sum to reported totals.

**Our call:** tech stack, hosting, live vs. scheduled refresh, exclusion rules, layout.

**Audience:** a non-technical owner understands it with zero explanation. Clear labels, no
jargon, logical flow: volume → pipeline → conversion → revenue.

## Environment setup (done / to do)

- [x] Cloud environment network access set to **Full** (GHL API reachable:
      `services.leadconnectorhq.com`).
- [ ] Add environment variables in the environment settings (never paste keys into chat
      or commit them):
      - `GHL_API_KEY` — sandbox API key / Private Integration token from the pinned message
      - `GHL_LOCATION_ID` — sandbox Location ID from the pinned message
- [ ] Start a new session so the variables load, then say:
      *"Continue Project 1 from PROJECT1_BRIEF.md"*.
- [ ] If the pinned message says which pipeline/tag identifies "our" agency, note it here.

## Plan

1. **Explore the data.** Read `GHL_API_KEY` / `GHL_LOCATION_ID` from the environment and pull
   contacts, opportunities and pipelines (API base `https://services.leadconnectorhq.com`,
   header `Version: 2021-07-28`). Save raw pulls outside the repo. Report what's messy to
   Sirine before building the page.
2. **Pick this agency's records.** Find the rule that separates them from other students'
   records (pipeline name, tag, location, naming pattern) and document it.
3. **Cleaning rules**, each with a count and a plain-English reason, to check for:
   - duplicate contacts (same email or phone, normalized)
   - test/internal leads (test names, internal or example domains, fake phones)
   - missing or unknown sources; inconsistent source spellings to merge
   - suspicious deal values (0, negative, extreme outliers, "won" with no value)
   - impossible dates (outside the 3-month window, in the future, closed before created)
   - opportunities without a contact, or in another pipeline
   - anything else found in the data
4. **Data build script** (`scripts/build-data.*`): pull → clean → aggregate by source →
   write `data/dashboard-data.json` (aggregates only, no personal data). The script asserts
   that stage counts sum to source totals and fails if not.
5. **Dashboard page** (`marketing-dashboard.html`, static, Chart.js, matches the site's
   style), top to bottom:
   1. Plain-English headline: where to put next month's budget, and why
   2. Lead volume by source (bar)
   3. Pipeline distribution across the 8 stages by source (stacked bar)
   4. Stage-to-stage conversion by source (funnel)
   5. Closed revenue by source (sorted bar)
   6. "Records removed and why" table, with counts per rule
   Every number is shown per source; no blended totals. Data tables under each chart.
6. **Refresh + hosting.** A scheduled GitHub Action runs the build script daily (key stored as
   GitHub repo secrets `GHL_API_KEY` / `GHL_LOCATION_ID`, never in the browser) and commits
   the updated JSON. Host on GitHub Pages; link it from `index.html`.
7. **Verify** in a browser (light/dark, phone width), then commit and push.
