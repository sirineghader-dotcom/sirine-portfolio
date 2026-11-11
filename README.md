# Sirine Ghader — Portfolio

A simple one-page portfolio website.

- `index.html`: the content (header, about, skills, contact)
- `style.css`: the design (colors, fonts, layout)
- `dashboard.html`: a demo marketing performance dashboard (KPI tiles plus daily spend and weekly ROAS charts) using generated sample data
- `marketing-dashboard.html`: live lead source dashboard (Project 1). Full write-up: [`PROJECT1_README.md`](PROJECT1_README.md). Reads `data/dashboard-data.json`, which `scripts/build_data.py` builds from the GoHighLevel API (pull → clean → aggregate by source). To refresh, run `python3 scripts/build_data.py` and commit the JSON. A daily GitHub Action (`.github/workflows/refresh-dashboard.yml`) is included, but GitHub has not registered it on this account yet, so refreshes are currently manual
- `ghl-lead-system.html`: a case study of the AI lead-to-booking system built with GoHighLevel and n8n
- `speed-to-lead.html`: a case study of the speed-to-lead revenue engine (n8n + GoHighLevel + Claude)
- `speed-to-lead/`: that project's n8n workflows, database schema, ad spend sheet, tests and live dashboard (`speed-to-lead/dashboard/`)

To view it, open `index.html` in any web browser. The live dashboard loads its data file, so serve the folder (GitHub Pages, or `python3 -m http.server`) rather than opening it as a file.
