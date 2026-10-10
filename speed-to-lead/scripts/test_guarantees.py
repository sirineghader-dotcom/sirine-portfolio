#!/usr/bin/env python3
"""
Proves "the real work" against a real Postgres, using the exact SQL inside the
n8n workflow files (read straight from workflows/*.json, not copied).

    createdb stl && psql -d stl -f speed-to-lead/sql/schema.sql
    STL_DSN="postgresql://localhost/stl" python3 speed-to-lead/scripts/test_guarantees.py

Values are inlined the way n8n's Postgres node (pg-promise) does it, so type
inference matches production. Every run uses fresh ids and cleans up after itself.
"""
import json
import os
import pathlib
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg

WF = pathlib.Path(__file__).resolve().parent.parent / "workflows"
DSN = os.environ.get("STL_DSN", "postgresql://postgres@localhost/stl")
RUN = uuid.uuid4().hex[:8]
results = []


def node_sql(workflow, node):
    data = json.loads((WF / f"{workflow}.json").read_text())
    return next(n for n in data["nodes"] if n["name"] == node)["parameters"]["query"]


def lit(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list)):
        v = json.dumps(v, default=str)
    return "'" + str(v).replace("'", "''") + "'"


def run(conn, workflow, node, *args):
    q = node_sql(workflow, node)
    q = re.sub(r"\$(\d+)", lambda m: lit(args[int(m.group(1)) - 1]), q)
    with conn.cursor() as cur:
        cur.execute(q)
        if cur.description is None:
            return []
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def plan(a):
    """Python mirror of the 'Plan: stage, cancels, new messages' Code node."""
    start = a["start_time"]
    now = datetime.now(timezone.utc)
    key = lambda t: f"{a['appointment_id']}:v{a['version']}:{t}"
    rem = [(t, ch, start - d) for t, ch, d in (
        ("reminder_24h_email", "Email", timedelta(hours=24)),
        ("reminder_24h_sms", "SMS", timedelta(hours=24)),
        ("reminder_2h_sms", "SMS", timedelta(hours=2)))
        if start - d > now + timedelta(minutes=10)]
    later = [{"sequence": "reminder", "template_key": t, "channel": ch, "send_at": s.isoformat()} for t, ch, s in rem]
    p = {
        "booked": ("call_booked", ["chase", "rebook", "reminder"], later, ["booking_confirmed_sms"]),
        "rescheduled": ("call_rescheduled", ["chase", "rebook", "reminder"], later, ["booking_rescheduled_sms"]),
        "cancelled": ("call_cancelled", ["chase", "reminder"],
                      [{"sequence": "rebook", "template_key": "cancel_rebook_2_email", "channel": "Email",
                        "send_at": (now + timedelta(days=2)).isoformat()}], ["cancel_rebook_1_sms"]),
        "noshow": ("no_show", ["chase", "reminder"],
                   [{"sequence": "rebook", "template_key": "noshow_rebook_1_sms", "channel": "SMS",
                     "send_at": (now + timedelta(minutes=15)).isoformat()}], []),
        "showed": ("showed", ["chase", "rebook", "reminder"], [], []),
    }[a["action"]]
    return {**{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in a.items()},
            "plan": {"lead_stage": p[0], "cancel": p[1], "why": a["action"],
                     "later": [{**m, "dedupe_key": key(m["template_key"])} for m in p[2]],
                     "now": [{"template_key": t, "dedupe_key": key(t)} for t in p[3]]}}


def appt_event(conn, appt, contact, status, start, event_at):
    ev = {"appointment_id": appt, "contact_id": contact, "status": status,
          "start_time": start.isoformat(), "event_at": event_at.isoformat(),
          "event_key": f"appt:{appt}:{status}:{start.isoformat()}"}
    claim = run(conn, "03-appointment-events", "Claim event (dedupe)", ev["event_key"], ev)[0]
    if not claim["is_new"]:
        return "duplicate", None
    a = run(conn, "03-appointment-events", "Apply state + decide action", ev)[0]
    if a["action"] in ("booked", "rescheduled", "cancelled", "noshow", "showed"):
        run(conn, "03-appointment-events", "Cancel old + schedule new", plan(a))
    return a["action"], a


def reserve(conn, lead_id, contact, template, key):
    r = run(conn, "02-send-message", "Reserve send slot",
            {"lead_id": lead_id, "contact_id": contact, "channel": "SMS", "template_key": template, "dedupe_key": key})[0]
    if r["reserved"]:
        run(conn, "02-send-message", "Mark sent + stamp first reply", key, f"msg-{RUN}-{key}")
    return r


def pending(conn, lead_id, seq=None):
    with conn.cursor() as cur:
        cur.execute("SELECT template_key, appointment_version FROM scheduled_messages WHERE lead_id = %s"
                    " AND status = 'pending'" + (" AND sequence = %s" if seq else ""),
                    (lead_id, seq) if seq else (lead_id,))
        return cur.fetchall()


def main():
    conn = psycopg.connect(DSN, autocommit=True)
    contact = f"c-{RUN}"
    now = datetime.now(timezone.utc)

    # 1. Same Meta lead delivered 3 times -> processed once
    lead = {"source": "meta", "event_key": f"meta:{RUN}", "first_name": "Dana", "last_name": "Lee",
            "email": f"dana+{RUN}@acme.io", "phone": "+15555550101", "company": "Acme",
            "answers": {"monthly_budget": "$5k-$10k"}, "opted_in_at": now.isoformat()}
    claims = [run(conn, "01-lead-intake", "Claim event (dedupe)", lead["event_key"], lead)[0] for _ in range(3)]
    check("same lead event x3 is processed once", [c["is_new"] for c in claims] == [True, False, False],
          f"is_new={[c['is_new'] for c in claims]}, hits={claims[-1]['hits']}")
    # 1b. ...and 3 copies arriving at the same instant on 3 connections
    burst = {**lead, "event_key": f"meta:burst-{RUN}"}
    conns = [psycopg.connect(DSN, autocommit=True) for _ in range(3)]
    with ThreadPoolExecutor(3) as pool:
        wins = list(pool.map(lambda c: run(c, "01-lead-intake", "Claim event (dedupe)", burst["event_key"], burst)[0]["is_new"], conns))
    check("3 simultaneous copies: exactly one wins", sorted(wins) == [False, False, True], str(wins))
    lead_id = run(conn, "01-lead-intake", "Create lead row", lead)[0]["lead_id"]
    run(conn, "01-lead-intake", "Save qualification",
        {"lead_id": str(lead_id), "contact_id": contact, "opportunity_id": f"o-{RUN}",
         "classification": "qualified", "score": 86, "reason": "B2B SaaS, founder, $8k/mo"})
    lead_id = str(lead_id)

    # 2. The same message can never go out twice
    r = [reserve(conn, lead_id, contact, "intake_qualified_sms", f"{lead_id}:intake_qualified_sms") for _ in range(3)]
    check("first reply reserved once out of 3 attempts", [x["reserved"] for x in r] == [True, False, False])
    with conn.cursor() as cur:
        cur.execute("SELECT first_reply_at IS NOT NULL FROM leads WHERE id = %s", (lead_id,))
        check("first_reply_at stamped on send", cur.fetchone()[0])
    run(conn, "01-lead-intake", "Schedule booking chase", lead_id)
    run(conn, "01-lead-intake", "Schedule booking chase", lead_id)
    check("booking chase queued once (3 steps) even if scheduled twice", len(pending(conn, lead_id, "chase")) == 3)

    # 3. Booked event x3 -> one confirmation, chase cancelled, reminders queued
    appt, start = f"a-{RUN}", (now + timedelta(days=3)).replace(microsecond=0)
    acts = [appt_event(conn, appt, contact, "booked", start, now)[0] for _ in range(3)]
    check("booking event x3 handled once", acts == ["booked", "duplicate", "duplicate"], str(acts))
    check("booking cancels the chase", len(pending(conn, lead_id, "chase")) == 0)
    rem_v1 = pending(conn, lead_id, "reminder")
    check("3 reminders queued for v1", len(rem_v1) == 3 and {v for _, v in rem_v1} == {1}, str(rem_v1))

    # 4. Reschedule kills old reminders
    new_start = start + timedelta(days=1)
    act, a = appt_event(conn, appt, contact, "booked", new_start, now + timedelta(seconds=5))
    rem_v2 = pending(conn, lead_id, "reminder")
    check("start time change is detected as a reschedule", act == "rescheduled" and a["version"] == 2, act)
    check("reschedule kills old reminders, queues new ones", {v for _, v in rem_v2} == {2} and len(rem_v2) == 3, str(rem_v2))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM scheduled_messages WHERE lead_id=%s AND sequence='reminder' "
                    "AND appointment_version=1 AND status='cancelled'", (lead_id,))
        check("the 3 v1 reminders are marked cancelled", cur.fetchone()[0] == 3)

    # 4b. A late, out-of-order copy of the original booking is ignored
    act, _ = appt_event(conn, appt, contact, "booked", start + timedelta(minutes=1), now - timedelta(minutes=5))
    check("out-of-order old event is ignored", act == "stale", act)

    # 5. Scheduler re-validates: a v1 reminder that slipped through would be skipped
    with conn.cursor() as cur:
        cur.execute("UPDATE scheduled_messages SET status='pending', send_at=now() - interval '1 minute' "
                    "WHERE lead_id=%s AND appointment_version=1", (lead_id,))
        cur.execute("UPDATE scheduled_messages SET send_at=now() - interval '1 minute' "
                    "WHERE lead_id=%s AND appointment_version=2 AND template_key='reminder_24h_sms'", (lead_id,))
    due = [d for d in run(conn, "04-scheduler", "Claim due messages") if d["lead_id"] == uuid.UUID(lead_id)]
    stale = [d for d in due if d["skip_reason"]]
    fresh = [d for d in due if not d["skip_reason"]]
    check("scheduler refuses reminders for the old time", len(stale) == 3 and all("changed" in d["skip_reason"] for d in stale))
    check("scheduler sends the reminder for the new time", len(fresh) == 1 and fresh[0]["template_key"] == "reminder_24h_sms")
    for d in stale:
        run(conn, "04-scheduler", "Mark skipped", d["schedule_id"], d["skip_reason"])
    due2 = [d for d in run(conn, "04-scheduler", "Claim due messages") if d["lead_id"] == uuid.UUID(lead_id)]
    check("a claimed row is never picked twice", due2 == [])
    rf = reserve(conn, lead_id, contact, fresh[0]["template_key"], fresh[0]["dedupe_key"])
    run(conn, "04-scheduler", "Mark result", fresh[0]["dedupe_key"], str(rf["reserved"]).lower(), "")

    # 6. No-show -> re-book sequence; cancel -> reminders die
    act, _ = appt_event(conn, appt, contact, "noshow", new_start, now + timedelta(seconds=10))
    check("no-show starts the re-book sequence", act == "noshow" and len(pending(conn, lead_id, "rebook")) == 1
          and len(pending(conn, lead_id, "reminder")) == 0)

    # 7. A human reply stops everything
    msg = {"message_id": f"m-{RUN}", "contact_id": contact, "direction": "outbound", "user_id": "u1",
           "event_key": f"msg:m-{RUN}"}
    run(conn, "05-human-takeover", "Claim event (dedupe)", msg["event_key"], msg)
    who = run(conn, "05-human-takeover", "Was it sent by automation?", msg["message_id"], contact)[0]
    check("a message GHL reports that we did not send is seen as human", not who["ours"] and who["lead_id"])
    ours = run(conn, "05-human-takeover", "Was it sent by automation?", f"msg-{RUN}-{lead_id}:intake_qualified_sms", contact)[0]
    check("our own automated message is recognised as ours", ours["ours"])
    p = run(conn, "05-human-takeover", "Pause lead + cancel queue", contact, "human_reply")[0]
    check("human reply pauses the lead and cancels its queue", p["leads_paused"] == 1 and p["messages_cancelled"] >= 1,
          f"paused={p['leads_paused']} cancelled={p['messages_cancelled']}")
    r = reserve(conn, lead_id, contact, "noshow_rebook_2_email", f"{lead_id}:anything-new")
    check("after takeover, even a brand-new message is refused", not r["reserved"] and r["paused"])
    act, _ = appt_event(conn, appt, contact, "booked", new_start + timedelta(days=2), now + timedelta(seconds=20))
    with conn.cursor() as cur:
        cur.execute("UPDATE scheduled_messages SET send_at=now() - interval '1 minute' WHERE lead_id=%s AND status='pending'", (lead_id,))
    due3 = [d for d in run(conn, "04-scheduler", "Claim due messages") if d["lead_id"] == uuid.UUID(lead_id)]
    check("reminders queued after takeover are skipped at send time", due3 and all("paused" in d["skip_reason"] for d in due3),
          str([d["skip_reason"] for d in due3]))

    # 8. Watchdog sees a lead nobody replied to
    silent = {**lead, "event_key": f"website:{RUN}", "source": "website",
              "opted_in_at": (now - timedelta(minutes=9)).isoformat()}
    run(conn, "01-lead-intake", "Claim event (dedupe)", silent["event_key"], silent)
    sid = run(conn, "01-lead-intake", "Create lead row", silent)[0]["lead_id"]
    found = [r for r in run(conn, "08-watchdog", "Find silent problems") if r["alert_key"] == f"no_first_reply:{sid}"]
    check("watchdog flags a lead with no reply after 5 min", len(found) == 1, found[0]["message"] if found else "")
    a1 = run(conn, "06-alert", "Record alert (dedupe)", f"t:{RUN}", "critical", "wf", "n", "msg", "", "{}")
    a2 = run(conn, "06-alert", "Record alert (dedupe)", f"t:{RUN}", "critical", "wf", "n", "msg", "", "{}")
    check("the same alert is delivered once, not every 5 minutes", len(a1) == 1 and a2 == [])

    # Clean up this run
    with conn.cursor() as cur:
        ids = (lead_id, str(sid))
        cur.execute("DELETE FROM sent_messages WHERE lead_id = ANY(%s::uuid[])", (list(ids),))
        cur.execute("DELETE FROM scheduled_messages WHERE lead_id = ANY(%s::uuid[])", (list(ids),))
        cur.execute("DELETE FROM appointments WHERE contact_id = %s", (contact,))
        cur.execute("DELETE FROM leads WHERE id = ANY(%s::uuid[])", (list(ids),))
        cur.execute("DELETE FROM processed_events WHERE event_key LIKE %s", (f"%{RUN}%",))
        cur.execute("DELETE FROM alerts WHERE alert_key LIKE %s", (f"%{RUN}%",))

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} guarantees hold")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
