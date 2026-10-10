-- =====================================================================
-- Speed-to-Lead Revenue Engine: Postgres schema
-- Run once against the database n8n uses (Supabase, Neon or any Postgres 13+).
--
-- GoHighLevel is the CRM the team works in. This database is the system's
-- memory: it is what makes the guarantees below hold even when GHL or Meta
-- send the same webhook three times.
--
--   processed_events  -> every inbound event is accepted at most once
--   sent_messages     -> every message is sent at most once (per dedupe key)
--   scheduled_messages-> reminders / chases / re-books, cancellable by row
--   leads.automation_paused -> a human reply stops everything for that lead
--   alerts            -> every failure is recorded and pushed to Slack + email
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- Settings: one place for IDs, links and alert targets.
-- Every workflow reads this table first, so nothing is hard-coded in n8n.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
  key   text PRIMARY KEY,
  value text NOT NULL
);

INSERT INTO settings (key, value) VALUES
  ('GHL_LOCATION_ID',            'REPLACE_ME'),
  ('GHL_PIPELINE_ID',            'REPLACE_ME'),
  ('STAGE_NEW_LEAD',             'REPLACE_ME'),
  ('STAGE_NEEDS_REVIEW',         'REPLACE_ME'),
  ('STAGE_QUALIFIED_LINK_SENT',  'REPLACE_ME'),
  ('STAGE_NOT_QUALIFIED',        'REPLACE_ME'),
  ('STAGE_CALL_BOOKED',          'REPLACE_ME'),
  ('STAGE_CALL_RESCHEDULED',     'REPLACE_ME'),
  ('STAGE_CALL_CANCELLED',       'REPLACE_ME'),
  ('STAGE_NO_SHOW',              'REPLACE_ME'),
  ('STAGE_SHOWED',               'REPLACE_ME'),
  ('BOOKING_LINK',               'https://api.leadconnectorhq.com/widget/booking/REPLACE_ME'),
  ('EMAIL_FROM_NAME',            'Northwind Growth'),
  ('TEAM_TIMEZONE',              'America/New_York'),
  ('ALERT_SLACK_WEBHOOK_URL',    'https://hooks.slack.com/services/REPLACE_ME'),
  ('ALERT_EMAIL_TO',             'owner@example.com'),
  ('CLAUDE_MODEL',               'claude-opus-5-5'),
  ('N8N_BASE_URL',               'https://your-n8n.example.com')
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------
-- Idempotency gate for every inbound webhook (leads, appointments, messages).
-- INSERT ... ON CONFLICT DO NOTHING RETURNING is atomic, so if the same
-- event arrives 3 times at the same millisecond, exactly one run proceeds.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_events (
  event_key   text PRIMARY KEY,           -- e.g. meta:leadgen:123, appt:abc:booked:2026-10-12T15:00Z
  kind        text NOT NULL,              -- lead | appointment | message
  received_at timestamptz NOT NULL DEFAULT now(),
  hits        int NOT NULL DEFAULT 1,     -- how many times we saw it (duplicates are counted, not processed)
  payload     jsonb
);

-- ---------------------------------------------------------------------
-- Leads: one row per opt-in. The dashboard reads from here.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_key         text UNIQUE NOT NULL REFERENCES processed_events(event_key),
  source            text NOT NULL CHECK (source IN ('meta','website','referral')),
  contact_id        text,                  -- GHL contact id
  opportunity_id    text,                  -- GHL opportunity id
  first_name        text,
  last_name         text,
  email             text,
  phone             text,
  company           text,
  answers           jsonb,                 -- form answers sent to the qualifier
  opted_in_at       timestamptz NOT NULL,
  first_reply_at    timestamptz,           -- set when the first automated message is accepted by GHL
  qualification     text CHECK (qualification IN ('qualified','not_qualified','needs_review')),
  score             int CHECK (score BETWEEN 0 AND 100),
  reason            text,
  stage             text NOT NULL DEFAULT 'new_lead',
  booked_at         timestamptz,           -- first time a call was booked
  showed_at         timestamptz,
  no_show_at        timestamptz,
  automation_paused boolean NOT NULL DEFAULT false,
  paused_reason     text,
  paused_at         timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS leads_contact_idx ON leads (contact_id, opted_in_at DESC);
CREATE INDEX IF NOT EXISTS leads_source_idx  ON leads (source, opted_in_at);

-- ---------------------------------------------------------------------
-- Appointments: the latest known state of each GHL appointment.
-- `version` goes up every time the start time changes. Reminders are tied
-- to a version, so a reschedule makes every older reminder unsendable.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS appointments (
  appointment_id text PRIMARY KEY,
  lead_id        uuid REFERENCES leads(id),
  contact_id     text NOT NULL,
  start_time     timestamptz NOT NULL,
  status         text NOT NULL,           -- booked | rescheduled | cancelled | noshow | showed
  version        int NOT NULL DEFAULT 1,
  last_event_at  timestamptz NOT NULL,    -- ignore events older than this (out-of-order delivery)
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Every future message lives here until it is sent or cancelled.
-- sequence: reminder | chase (qualified, not booked) | rebook (no-show / cancel)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduled_messages (
  id                  bigserial PRIMARY KEY,
  lead_id             uuid NOT NULL REFERENCES leads(id),
  contact_id          text NOT NULL,
  appointment_id      text,
  appointment_version int,
  sequence            text NOT NULL CHECK (sequence IN ('reminder','chase','rebook')),
  template_key        text NOT NULL,
  channel             text NOT NULL CHECK (channel IN ('SMS','Email')),
  send_at             timestamptz NOT NULL,
  status              text NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','sending','sent','cancelled','skipped','failed')),
  dedupe_key          text UNIQUE NOT NULL,
  cancel_reason       text,
  locked_at           timestamptz,
  done_at             timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sched_due_idx ON scheduled_messages (send_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS sched_lead_idx ON scheduled_messages (lead_id, status);

-- ---------------------------------------------------------------------
-- The send ledger. A row is reserved BEFORE calling GHL; the primary key
-- makes a second send with the same dedupe key impossible.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sent_messages (
  dedupe_key     text PRIMARY KEY,
  lead_id        uuid REFERENCES leads(id),
  contact_id     text NOT NULL,
  channel        text NOT NULL,
  template_key   text NOT NULL,
  status         text NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','sent','failed')),
  ghl_message_id text,
  error          text,
  reserved_at    timestamptz NOT NULL DEFAULT now(),
  sent_at        timestamptz
);
CREATE INDEX IF NOT EXISTS sent_msgid_idx ON sent_messages (ghl_message_id);
CREATE INDEX IF NOT EXISTS sent_contact_idx ON sent_messages (contact_id, reserved_at DESC);

-- ---------------------------------------------------------------------
-- Alerts: every failure lands here and is pushed to Slack + email.
-- alert_key de-duplicates watchdog alerts so one stuck lead = one alert.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
  id            bigserial PRIMARY KEY,
  alert_key     text UNIQUE,
  severity      text NOT NULL DEFAULT 'error' CHECK (severity IN ('warning','error','critical')),
  workflow      text,
  node          text,
  message       text NOT NULL,
  execution_url text,
  context       jsonb,
  delivered     boolean NOT NULL DEFAULT false,
  resolved      boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Ad spend, one row per day per source per line item (load data/ad-spend.csv)
--   \copy ad_spend (date, source, line_item, amount_usd) FROM 'data/ad-spend.csv' CSV HEADER
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ad_spend (
  date       date NOT NULL,
  source     text NOT NULL CHECK (source IN ('meta','website','referral')),
  line_item  text NOT NULL,
  amount_usd numeric(10,2) NOT NULL,
  PRIMARY KEY (date, source, line_item)
);

-- ---------------------------------------------------------------------
-- Dashboard view: per-source funnel. Never blended: GROUP BY source only.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_source_funnel AS
SELECT
  l.source,
  count(*)                                                         AS leads,
  count(*) FILTER (WHERE l.qualification = 'qualified')            AS qualified,
  count(*) FILTER (WHERE l.booked_at IS NOT NULL)                  AS booked,
  count(*) FILTER (WHERE l.showed_at IS NOT NULL)                  AS showed,
  count(*) FILTER (WHERE l.no_show_at IS NOT NULL)                 AS no_shows,
  percentile_cont(0.5) WITHIN GROUP (
    ORDER BY extract(epoch FROM l.first_reply_at - l.opted_in_at) / 60.0
  )                                                                AS median_minutes_to_first_reply,
  (SELECT sum(amount_usd) FROM ad_spend s WHERE s.source = l.source) AS spend_usd
FROM leads l
GROUP BY l.source;
