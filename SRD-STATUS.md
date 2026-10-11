# Where the system stands against the SRD

Checked on 11 October 2026 against `main` at 6053cc2 (rows 77 and 94 updated since), requirement by
requirement, from "AI_Multilingual_CRM_SRD_Updated (2).docx". Each row was
checked in the code and its tests, not from earlier notes.

**Met**: built, and seen working here (tests, and where it says so a real
replay or a browser check).
**Waiting**: built, but it can only be proved with an access you do not have
yet (Plivo, the paid Groq key, the SMS gateway, a storage bucket, recordings
in the other languages) or with real users and real load.
**Not met**: missing or short of what the SRD says, with the reason.

Totals: 121 requirements: 82 met, 25 waiting, 14 not met.

## 1. Scope and users (SRD 1.2, 1.3)

| # | Requirement | State | Notes |
|---|---|---|---|
| 1 | Live transcription in Tamil, Telugu, Kannada, Malayalam and English | Waiting | All five are accepted. English and Tamil-English were replayed for real. Telugu, Kannada and Malayalam have never been heard by the system: they need recordings. |
| 2 | Speaker identification | Met | Separate Plivo tracks give the speaker outright; on one mixed stream voices and wording decide. One limit: a quick reply can be joined to the other person's line (checklist, section 10). |
| 3 | Language auto-detection | Met | Each line carries its languages. Seen wrong once in five replays (an English greeting tagged English and Telugu). |
| 4 | Sentiment per utterance: positive, neutral, negative, frustrated, escalating | Met | Each customer line is rated with one of the five and a confidence. |
| 5 | Sentiment shown live to supervisors and executives | Met | Coloured lines and a tone panel on the call screen; tone per call on Live Calls. |
| 6 | Next-question suggestions to the executive, in real time, from the live transcript | Met | Up to three, written with the live analysis, then checked against what the customer already said. |
| 7 | Suggestions make sure no category goes unexplored | Met | Questions are written for complaints not yet asked about; an alert is raised for one left unasked. |
| 8 | Every complaint classified into one or more of the ten categories | Met | Cost, Hygiene, Hospitality, Service Quality, Turnaround Time, Communication, Parts Availability, Staff Behaviour, Documentation, Other. |
| 9 | Reported as trend data, heatmaps and root-cause summaries | Met | Reports page: trend by day or week, category by location, root causes with the customer's words. |
| 10 | Executives: live guidance, sentiment cues, structured call guidance | Met | The live call screen. |
| 11 | Managers: category dashboards with trend lines; drill-down by category, location, period | Met | Reports with filters; a root cause links to its calls. |
| 12 | QA and leadership: automated call auditing with category-level scoring | Met | An audit score per call with a score per category and the reason for each point. Fixed rules, shown as estimates. |
| 13 | QA and leadership: evaluate executive performance | Met | Scorecard per executive on Reports > Performance. |
| 14 | Admins: user management, access, system settings | Met | Administration: users, roles, locations, categories. Other settings are in `.env`. |
| 15 | Admins: monitor health, AI monitoring | Met | `/health`, `/metrics`, Prometheus alerts, Grafana dashboard, the AI log. |
| 16 | Admins: model training, evaluate model performance, deploy updates | Not met | No model is trained here: the models are Groq's and Sarvam's. What exists: the model is chosen in `.env`, the AI Improvement Center turns reviewed corrections into better instructions, and `scripts/measure_accuracy.py` scores a set of labelled calls. |

## 2. Functions and modes (SRD 2.1)

| # | Requirement | State | Notes |
|---|---|---|---|
| 17 | Live Call Mode: transcription, sentiment, classification and guidance together | Met | Seen on real replays in both analysis speeds. |
| 18 | Category Classification Mode | Met | |
| 19 | Executive Guidance Mode | Met | |
| 20 | Report Generation Mode: post-call reports, sentiment summaries, trend dashboards | Met | Post-call summary per call; Reports with tone summary and trend. |
| 21 | Analytics Mode | Met | Reports > Performance. |
| 22 | Quality Audit Mode | Met | Audit panel on a finished call; averages on the scorecard. |
| 23 | Supervisor Monitoring Mode | Met | Live Calls page: every call in progress with tone, complaints, escalation and alerts. |

## 3. What is captured (SRD 2.2)

| # | Requirement | State | Notes |
|---|---|---|---|
| 24 | Audio stream, call duration, timestamps | Met | |
| 25 | Caller ID | Waiting | Stored from Plivo's "From" and matched to the customer file. Needs a real Plivo call. |
| 26 | Executive ID | Waiting | From who answered (Plivo) or who is signed in (web app). The Plivo side is built to its documentation and unverified. |
| 27 | Language detected, speaker segments | Met | Per line. |
| 28 | Complaint segments with category labels | Met | Each line carries the categories it raises. |
| 29 | Confidence score per classification | Met | Stored and shown ("90% sure"). |
| 30 | Multi-category flag where one utterance covers several issues | Met | "Several issues" on the line. |
| 31 | Per-utterance sentiment score and emotion label | Met | |
| 32 | Escalation risk level | Met | None, low, medium, high, critical, with the reasons. |
| 33 | Sentiment trajectory over the call | Met | Tone timeline on the call; tone at start and end in reports. |
| 34 | Context window fed to the next-question engine | Met | The full request is in the AI log (30 days). |
| 35 | Suggested questions generated; accepted or skipped by the executive | Met | Accept and Skip are recorded per question. |
| 36 | CSAT prediction | Met | An estimate by fixed rules, labelled as an estimate. |
| 37 | Complaint category frequency index per location and period | Met | The heatmap and category totals. |
| 38 | Executive question coverage score | Met | Share of complaints the executive asked about. |
| 39 | First Call Resolution rate | Met | By fixed rules. |
| 40 | Repeat complaint probability | Met | Reported as the repeat rate among known customers: a measured rate, not a prediction per customer. |
| 41 | Customer churn risk score | Met | Low, medium or high, by fixed rules. |
| 42 | Sentiment trend per call and per executive | Met | |
| 43 | Audio sampling 16 to 48 kHz | Not met | The system asks Plivo for 16 kHz and also takes 8 kHz. Nothing above 16 kHz is handled: a phone line does not carry more. |
| 44 | Live transcription under 2 seconds | Not met | Speech is transcribed when the speaker pauses. In replays a line appeared about 1 to 3 seconds after the speaker stopped (measured to the nearest 2 seconds), so longer lines are later than 2 seconds after they began. Meeting this needs a streaming speech recogniser, which is a different integration. |
| 45 | Complaint classification under 3 seconds per utterance | Waiting | With `LIVE_ANALYSIS_SPEED=fast` each analysis took about 1 second after the line was transcribed. The free Groq key cannot sustain it (it waited 35 seconds once). Standard mode analyses every 30 seconds by your earlier decision. |
| 46 | Next question under 1.5 seconds after the utterance ends | Not met | In fast mode the questions follow the line by about 1 to 2 seconds, on top of the 1 to 3 seconds the line itself takes. From the end of the utterance that is roughly 2.5 to 5 seconds. The same streaming recogniser would be needed. |
| 47 | Speech recognition accuracy at least 95% | Waiting | Never measured: it needs recordings with a written-down transcript, per language. The script is ready. |
| 48 | Classification accuracy at least 92% | Waiting | On five test calls with my own labels: 15 of 17 categories. Too few to claim anything. |
| 49 | Multi-category detection at least 88% | Waiting | 2 of 3 on the same five calls. |
| 50 | Sentiment classification at least 90% | Waiting | 3 of 5 exact, 5 of 5 on the right side, on the same five calls. |
| 51 | Next-question relevance at least 85%, judged by people | Waiting | Scored from Accept and Skip once executives use it (at least 30 choices). |
| 52 | Timestamps with millisecond precision | Met | Times are stored in seconds with fractions. |
| 53 | Audio, transcript, telephony events and AI outputs in step | Met | All carry call time; AI requests are logged against the call. |
| 54 | CRM records in step | Not met | Left out by your decision: customers come from a file, nothing is written back to a CRM. |

## 4. Logging and storage (SRD 2.3)

| # | Requirement | State | Notes |
|---|---|---|---|
| 55 | Local encrypted storage | Met | Recordings are encrypted file by file. The database itself is not encrypted by the application: use an encrypted disk for that. |
| 56 | On-premise server (optional) | Met | Runs from Docker on any server. |
| 57 | Continuous call recording | Waiting | Built and off by default (it needs the customer's consent). Never run on a real phone call. |
| 58 | Event-based logging | Met | Structured server logs with a request id. |
| 59 | AI inference logs | Met | Every request to the AI, per call. |
| 60 | Audit logs | Met | Who did what, when. |
| 61 | Automated backups | Waiting | A real backup of the local database was made and read back. Running daily into a bucket needs the bucket. |
| 62 | Data replication | Met | Tried with two throwaway databases: followed, read-only, promoted. Not tried across two machines. |
| 63 | Integrity verification | Met | Daily checksum comparison of recordings, with restore from the copy. |
| 64 | HTTPS APIs | Waiting | The application speaks plain HTTP behind a proxy that must add TLS. That proxy is yours to set up. |
| 65 | Secure cloud storage and transcript archive | Waiting | Built for any S3-compatible bucket and tested against a stand-in and a folder. No real bucket yet. |
| 66 | AI model updates | Met | A model is changed by a setting and a restart. |
| 67 | Remote monitoring | Met | Prometheus, Grafana, e-mail alerts (seen arriving in the local mail catcher). |
| 68 | Data export | Met | CSV, Excel and PDF. |
| 69 | Backup and disaster recovery | Not met | Backups, restore steps and a replica exist. Switching over is manual, and nothing fails over by itself: automatic failover was set aside by your decision. |

## 5. Screens and indicators (SRD 2.4)

| # | Requirement | State | Notes |
|---|---|---|---|
| 70 | Transcript panel: speaker labels, language indicators, sentiment colour per segment | Met | Five colours rather than three, one per tone. |
| 71 | Next-question panel, ranked by relevance to the category detected | Met | |
| 72 | Category panel: categories detected so far, with confidence | Met | |
| 73 | Report dashboard filtered by category, location, executive, date range, sentiment | Met | Also by call direction. |
| 74 | Supervisor dashboard: live sentiment and category feeds across all active calls | Met | Built to hold 500 calls; proved with 500 seeded records in tests, not with 500 real calls. |
| 75 | Call status: Incoming, Outgoing, Connected, On Hold, Ended | Met | Incoming and Outgoing ringing need a Plivo call to be seen. On Hold is what the executive marks in the web app. |
| 76 | AI status: Listening, Transcribing, Classifying, Generating next question, Updating sentiment | Met | "Updating sentiment" is too brief to be seen, as one request does both. |
| 77 | Alert: negative customer sentiment detected | Met | Raised when the call's tone is negative, frustrated or escalating and the analysis is at least 60% sure (a setting); cleared when the customer calms down. |
| 78 | Alert: escalation risk | Met | Escalation card and the Escalations queue. |
| 79 | Alert: uncovered complaint category | Met | |
| 80 | Alert: high-severity category | Met | Which categories count is a setting (Hygiene by default; the SRD's example also names safety, which is not one of the ten categories). |
| 81 | Alert: classification confidence below threshold | Met | |
| 82 | Alert: poor call audio quality | Met | Judged from audio that transcribes to nothing, as Sarvam gives no confidence. |
| 83 | Logging status: Recording, Archive Complete, Export Ready | Met | Recording and Archive Complete need a recorded call to be seen; Archive Complete was seen with copies turned on. |

## 6. Maintenance (SRD 2.5)

| # | Requirement | State | Notes |
|---|---|---|---|
| 84 | AI model retraining on new complaint patterns | Not met | No retraining (see row 16). New patterns are found as "emerging themes" and reviewed corrections improve the instructions. |
| 85 | Category taxonomy updates | Met | An admin adds, renames and retires categories; accepted themes become categories. |
| 86 | Next-question evaluation and relevance review | Met | Accept and Skip counts per executive; the accuracy script scores them. |
| 87 | Performance monitoring and database optimisation | Met | Metrics and alerts; indexes where the busy screens read. No automatic tuning. |
| 88 | Backup verification | Met | Each backup is checked as complete in the storage. A restore drill is a manual step in `DEPLOYMENT.md`. |
| 89 | Report template updates | Not met | Report layouts are in the code: changing one is a code change. |
| 90 | User access reviews | Met | The user list with roles, and the audit log of who did what. |

## 7. Technical, constraints and performance (SRD 3, 4, 5)

| # | Requirement | State | Notes |
|---|---|---|---|
| 91 | REST APIs | Met | |
| 92 | CRM APIs | Not met | Left out by your decision. |
| 93 | Telephony APIs | Waiting | Plivo, incoming and outgoing, built to its documentation. Needs a real call. |
| 94 | Report export: CSV, PDF, Excel, filtered by category | Met | All three, with the filters applied. The PDF prints Tamil, Telugu, Kannada and Malayalam in bundled Noto fonts; text copied out of the PDF in those scripts does not copy back correctly (use Excel or CSV for that). |
| 95 | Cloud, on-premise or hybrid | Met | |
| 96 | 24/7 operation, at least 99.9% availability | Waiting | Nothing here has run long enough, or on real infrastructure, to say. |
| 97 | Minimal training; clear next-question and category feed | Waiting | Built; only real executives can say. |
| 98 | One-click categorised report generation | Met | |
| 99 | Mobile-friendly, desktop and tablet | Met | Every page checked at phone and tablet width for sideways scrolling. Not a design review of each page. |
| 100 | Role-based access: executive, supervisor, management report view | Met | Plus admin. The management role is refused everything but reports and finished calls. |
| 101 | Headset and VoIP device support | Waiting | Audio is handled by Plivo and the executive's phone or softphone; the web app itself uses no microphone. |
| 102 | Secure handling of customer data | Met | Sign-in with roles, encrypted recordings and copies, retention periods, audit log, production start-up checks. No penetration test (row 107). |
| 103 | Compliance with data protection regulations | Not met | No legal review has been done. The pieces a review will ask for exist: consent-gated recording, retention, access log. |
| 104 | Scalable, cloud-native architecture | Waiting | Several servers can share calls through Redis. Tried on one laptop only. |
| 105 | 500 or more concurrent calls | Waiting | With stand-in speech and AI services a laptop kept up with 100 calls and just missed at 200. 500 needs real servers and the paid keys. |
| 106 | Dashboard response under 3 seconds | Waiting | Live Calls reads 500 calls in four database reads. Not timed under real load. |
| 107 | Data reliability 99.99%, data loss under 0.001% | Not met | Nothing measures this. Backups, a replica and integrity checks reduce the risk; a figure needs months of real operation. |

## 8. Testing the SRD asks for (SRD 6)

| # | Requirement | State | Notes |
|---|---|---|---|
| 108 | Unit tests: sentiment, classifier, next-question, taxonomy, telephony | Met | 2,674 tests, all passing. |
| 109 | Unit tests: speech recognition per language | Waiting | Needs recordings in each language. |
| 110 | System test: live call end to end | Met | Five real replays on 11 October 2026. |
| 111 | System test: CRM synchronisation | Not met | Left out by your decision. |
| 112 | System test: reports, guidance panel, supervisor dashboard | Met | In tests and in the browser. |
| 113 | Data validation: accuracy per language and per function | Waiting | Rows 47 to 51. |
| 114 | Operational: executives across all categories; adoption | Waiting | Needs real executives. |
| 115 | Operational: mixed-language conversations | Met | Tamil-English replayed twice. |
| 116 | Operational: high-volume concurrent calls | Waiting | Row 105. |
| 117 | Environmental: network interruption and transcript recovery | Met | A dropped and reconnected stream carries on, in tests. Not tried on a real line. |
| 118 | Environmental: cloud failover and disaster recovery | Not met | Set aside by your decision (row 69). |
| 119 | Environmental: security and penetration testing | Not met | Set aside by your decision. Two internal code reviews for security were done; no outside test. |
| 120 | Environmental: adding new categories | Met | |
| 121 | Environmental: telephony integration | Waiting | Row 93. |

## What is not met, in one place

By your decision:

- CRM connection and its tests (rows 54, 92, 111).
- Automatic failover, disaster-recovery testing, penetration testing (rows 69, 118, 119).

Needs a different speech recogniser:

- Transcript under 2 seconds and next question under 1.5 seconds (rows 44, 46).

Not what this kind of system does:

- Training or retraining models (rows 16, 84). Audio above 16 kHz (row 43).

Needs something outside the software:

- A data-protection review (row 103). A measured reliability figure (row 107).
- Report layouts changeable without a code change (row 89): not asked for in any detail by the SRD.
