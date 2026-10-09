# Sirine Ghader — Portfolio

A simple one-page portfolio website.

- `index.html`: the content (header, about, skills, contact)
- `style.css`: the design (colors, fonts, layout)
- `dashboard.html`: a demo marketing performance dashboard (KPI tiles plus daily spend and weekly ROAS charts) using generated sample data
- `marketing-dashboard.html`: live lead source dashboard (Project 1). Reads `data/dashboard-data.json`, which `scripts/build_data.py` builds from the GoHighLevel API (pull → clean → aggregate by source). A GitHub Action (`.github/workflows/refresh-dashboard.yml`) reruns it daily using the `GHL_API_KEY` / `GHL_LOCATION_ID` repo secrets
- `ghl-lead-system.html`: a case study of the AI lead-to-booking system built with GoHighLevel and n8n

To view it, open `index.html` in any web browser. The live dashboard loads its data file, so serve the folder (GitHub Pages, or `python3 -m http.server`) rather than opening it as a file.
