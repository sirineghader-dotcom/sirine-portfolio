#!/usr/bin/env bash
# Sends test events to the n8n webhooks: the script for the Loom recording.
#
#   export N8N=https://your-n8n.example.com/webhook   # production webhook base URL
#   ./simulate.sh meta            # a qualified Meta lead
#   ./simulate.sh website         # a website lead that needs review
#   ./simulate.sh referral        # a referral that is not qualified (B2C)
#   ./simulate.sh dupes           # the same Meta lead 3 times at once
#   ./simulate.sh book <contactId> <appointmentId> [start ISO]
#   ./simulate.sh reschedule <contactId> <appointmentId> <new start ISO>
#   ./simulate.sh cancel <contactId> <appointmentId> <start ISO>
#   ./simulate.sh noshow <contactId> <appointmentId> <start ISO>
#   ./simulate.sh human <contactId>   # a team member replies by hand
#   ./simulate.sh broken          # a lead with no email or phone -> alert
set -euo pipefail
: "${N8N:?set N8N to your n8n webhook base, e.g. https://x.app.n8n.cloud/webhook}"
RUN=${RUN:-$(date +%s)}

post() { curl -sS -X POST "$N8N/$1" -H 'Content-Type: application/json' -d "$2"; echo; }

meta_lead() {  # Meta Lead Ads webhook shape, with field_data included
  cat <<JSON
{"object":"page","entry":[{"id":"1029384756","time":$(date +%s),"changes":[{"field":"leadgen","value":{
  "leadgen_id":"$1","page_id":"1029384756","form_id":"88123","ad_name":"B2B Pipeline Audit - Lookalike 3%",
  "created_time":$(date +%s),
  "field_data":[
    {"name":"full_name","values":["Dana Lee"]},
    {"name":"email","values":["dana.lee+$RUN@example.com"]},
    {"name":"phone_number","values":["+15555550101"]},
    {"name":"company_name","values":["Brightpath Software"]},
    {"name":"job_title","values":["Founder & CEO"]},
    {"name":"company_size","values":["25-50"]},
    {"name":"monthly_budget","values":["\$8,000 - \$15,000"]},
    {"name":"timeline","values":["This month"]},
    {"name":"biggest_challenge","values":["Our cost per demo on LinkedIn doubled; we need a cheaper pipeline source."]}
  ]}}]}]}
JSON
}

case "${1:-}" in
  meta)
    post stl/lead/meta "$(meta_lead "lg_$RUN")" ;;
  dupes)
    # Meta retries webhooks; simulate 3 copies arriving together.
    body=$(meta_lead "lg_dupe_$RUN")
    for _ in 1 2 3; do post stl/lead/meta "$body" & done; wait ;;
  website)
    post stl/lead/website "{\"submission_id\":\"web_$RUN\",\"first_name\":\"Marco\",\"last_name\":\"Ruiz\",
      \"email\":\"marco+$RUN@example.com\",\"phone\":\"5555550102\",\"company_name\":\"Ruiz Logistics\",
      \"job_title\":\"Operations Manager\",\"company_size\":\"600+\",\"monthly_budget\":\"\$3,000 - \$5,000\",
      \"timeline\":\"Next quarter\",\"biggest_challenge\":\"Exploring options for the marketing team\",
      \"utm_campaign\":\"google-b2b-lead-gen\"}" ;;
  referral)
    post stl/lead/referral "{\"referral_id\":\"ref_$RUN\",\"first_name\":\"Priya\",\"last_name\":\"Shah\",
      \"email\":\"priya+$RUN@example.com\",\"phone\":\"5555550103\",\"company_name\":\"Glow Nail Studio\",
      \"job_title\":\"Owner\",\"company_size\":\"1-5\",\"monthly_budget\":\"Under \$1,000\",\"timeline\":\"ASAP\",
      \"notes\":\"Wants more walk-in customers for her salon\",\"referred_by\":\"Jordan Kim (client)\"}" ;;
  broken)
    post stl/lead/website "{\"submission_id\":\"bad_$RUN\",\"first_name\":\"NoContact\"}" ;;
  book|reschedule)
    start=${4:-$(date -u -d '+2 days 15:00' +%Y-%m-%dT%H:%M:%SZ)}
    post stl/appointment "{\"type\":\"AppointmentUpdate\",\"appointment\":{\"id\":\"$3\",\"contactId\":\"$2\",
      \"startTime\":\"$start\",\"appointmentStatus\":\"confirmed\",\"dateUpdated\":\"$(date -u +%FT%TZ)\"}}" ;;
  cancel)
    post stl/appointment "{\"type\":\"AppointmentUpdate\",\"appointment\":{\"id\":\"$3\",\"contactId\":\"$2\",
      \"startTime\":\"$4\",\"appointmentStatus\":\"cancelled\",\"dateUpdated\":\"$(date -u +%FT%TZ)\"}}" ;;
  noshow)
    post stl/appointment "{\"type\":\"AppointmentUpdate\",\"appointment\":{\"id\":\"$3\",\"contactId\":\"$2\",
      \"startTime\":\"$4\",\"appointmentStatus\":\"noshow\",\"dateUpdated\":\"$(date -u +%FT%TZ)\"}}" ;;
  human)
    post stl/message "{\"type\":\"OutboundMessage\",\"messageId\":\"manual_$RUN\",\"contactId\":\"$2\",
      \"direction\":\"outbound\",\"userId\":\"team_member_1\",\"messageType\":\"SMS\",
      \"body\":\"Hi Dana, Sam here. Happy to jump on a quick call today instead?\"}" ;;
  *)
    sed -n '2,15p' "$0"; exit 1 ;;
esac
