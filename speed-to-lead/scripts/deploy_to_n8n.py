#!/usr/bin/env python3
"""
Creates (or updates) all STL workflows in an n8n instance through its public API
and wires the sub-workflow / error-workflow IDs together.

    export N8N_URL=https://your-n8n.example.com
    export N8N_API_KEY=...            # n8n -> Settings -> n8n API
    python3 speed-to-lead/scripts/deploy_to_n8n.py [--activate]

Credentials are not created here: after the first deploy, open each workflow
once and select your "STL Postgres", "GHL Private Integration", "Anthropic API"
and "Alerts SMTP" credentials, then run again with --activate.
"""
import json
import os
import pathlib
import sys
import urllib.request

WF_DIR = pathlib.Path(__file__).resolve().parent.parent / "workflows"
BASE = os.environ["N8N_URL"].rstrip("/") + "/api/v1"
KEY = os.environ["N8N_API_KEY"]
# Sub-workflows first so their IDs exist before the callers are created.
ORDER = ["06-alert", "07-error-handler", "02-send-message", "01-lead-intake", "03-appointment-events",
         "04-scheduler", "05-human-takeover", "08-watchdog", "09-dashboard-api"]
PLACEHOLDER = {"06-alert": "__WF_ALERT__", "07-error-handler": "__WF_ERROR_HANDLER__",
               "02-send-message": "__WF_SEND_MESSAGE__"}


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, headers={
        "X-N8N-API-KEY": KEY, "Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def main():
    existing = {w["name"]: w["id"] for w in api("GET", "/workflows?limit=250").get("data", [])}
    ids = {}
    for f in ORDER:
        raw = (WF_DIR / f"{f}.json").read_text()
        for src, ph in PLACEHOLDER.items():
            if src in ids:
                raw = raw.replace(ph, ids[src])
        wf = json.loads(raw)
        if f == "07-error-handler" or "__WF_ERROR_HANDLER__" in raw:
            wf["settings"].pop("errorWorkflow", None)  # set on the second pass below
        body = {k: wf[k] for k in ("name", "nodes", "connections", "settings")}
        if wf["name"] in existing:
            ids[f] = existing[wf["name"]]
            api("PUT", f"/workflows/{ids[f]}", body)
            print("updated", wf["name"], ids[f])
        else:
            ids[f] = api("POST", "/workflows", body)["id"]
            print("created", wf["name"], ids[f])

    # Second pass: every workflow except the handler reports errors to the handler.
    for f in ORDER:
        if f == "07-error-handler":
            continue
        wf = api("GET", f"/workflows/{ids[f]}")
        wf["settings"]["errorWorkflow"] = ids["07-error-handler"]
        api("PUT", f"/workflows/{ids[f]}", {k: wf[k] for k in ("name", "nodes", "connections", "settings")})

    if "--activate" in sys.argv:
        for f in ORDER:
            if f in PLACEHOLDER:
                continue  # sub-workflows and the error handler do not need activating
            api("POST", f"/workflows/{ids[f]}/activate")
            print("activated", f)
    print(json.dumps(ids, indent=2))


if __name__ == "__main__":
    main()
