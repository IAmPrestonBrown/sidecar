# Sidecar: Hypothesis Platform Spec

Working name: **Sidecar**. Status: approved for build, 2026-10-07.

Each project has two companion documents: a research brief (purpose and
hypotheses) and an outreach brief (who to contact and how to write to them).
`examples/` has a fictional pair. Where this spec and a project's outreach brief
differ on outreach, the outreach brief wins.

Sidecar is a single-user macOS desktop app for running customer discovery end to
end: organize projects and hypotheses, find and email prospects, run interviews with
the live call coach, and turn what you hear into reviewed evidence for or against
each hypothesis.

It grows out of the Interview Coach. The live call pipeline (recording, live
transcription, coaching cards, MARK, ASK NEXT, batch transcript) stays as it is and
becomes one part of a larger app.

## 1. Principles

1. **Nothing leaves without review.** No email, follow-up, pipeline change, prospect,
   or piece of evidence takes effect until the user approves it. The app proposes; the
   user decides. Approving many items at once is allowed, but it is always an explicit
   action.
2. **Evidence hygiene is built in.** The app keeps the research brief's rules visible
   in the data model: behavior versus opinion, capability versus adoption, one person
   versus independent organizations, problem hypotheses versus the solution hypothesis.
3. **Local, private, and portable.** Each project is a plain folder of JSON,
   Markdown, and audio files on this Mac. The folder is the database: it can be
   copied, versioned, exported, or pasted into another tool. Secrets live in the
   macOS Keychain, never in the folder. No cloud backend, no accounts, no telemetry.
4. **Quiet.** No sounds, no system notifications, no badges that demand attention
   during a call. The live call window keeps its current rules.
5. **Native feel.** Follows the macOS Human Interface Guidelines: sidebar, toolbar,
   inspector, system font, system controls, keyboard first. No decorative gradients,
   illustrations, glows, or "AI" styling.
6. **Reliability first for calls.** The coach's recording guarantees (see
   `docs/coach.md`) still apply in full. A failure in email, search, or the
   database never stops a recording.

## 2. Scope

### In scope (v1)
- Projects, each with a research brief and a set of hypotheses.
- Hypothesis tracking with supporting, contradicting, and mixed evidence.
- A review inbox for evidence proposed from calls.
- People and organizations, with an outreach pipeline.
- Gmail connection: send approved emails, read replies.
- Campaigns: an email outline, a sequence (first email plus follow-ups), and an
  AI-written draft per person that follows the outline.
- An email review queue and paced sending.
- Reply detection with suggested pipeline moves (reviewed, never automatic).
- Calls: the existing live call coach, plus a call library and call review page.
- Prospect sourcing: CSV import, manual entry, and AI-assisted research with sources
  (reviewed before anyone is added).
- A Tauri desktop shell with native window chrome, menus, and keyboard shortcuts.

### Not in v1
- Cloud sync, teams, or multiple users.
- Outlook or IMAP accounts (the email layer is designed so they can be added).
- Open or click tracking (it hurts deliverability and is unreliable).
- Automatic sending of anything.
- Calendar integration. Booked calls are entered by hand or created from a reply.
- Windows and Linux builds (Tauri allows them later; v1 targets macOS only).
- Bulk scraping of websites. AI research uses targeted web search with cited sources.

## 3. Concepts and data model

```
Project folder
 ├── Brief, outreach brief (markdown)
 ├── Hypothesis (H1..Hn)            statement, kind (problem | solution), status
 │     └── Evidence ─────────────┐  linked to one or more hypotheses
 ├── Organization ── Person      │  global duplicate tracking, segments, sources
 │                    └── Outreach (stage, messages, follow-ups, scheduling)
 ├── Wave                        │  a batch of outreach; one person per org per wave
 ├── Call ───────────────────────┤  audio, transcripts, coach outputs, marks
 │     └── Proposed evidence ────┘  waits in the review inbox
 └── Activity log                   every approval, send, stage change, and edit
```

### 3.1 Storage: the project folder

Projects live in `~/Documents/Sidecar/<project-slug>/` (the root is configurable).
Every file is human-readable and documented by a `README.md` in the folder.

```
<project>/
  README.md               what each file is, for people and other tools
  project.json            name, slug, settings, coach profile, banned phrases
  brief.md                research brief (read by the coach)
  outreach_brief.md       outreach rules and email template (read by the writer)
  hypotheses.json         list of hypotheses and the competing explanation
  organizations.json      list of organizations
  people.json             list of people, each with outreach state
  evidence.json           list of evidence items with hypothesis links
  messages.json           every drafted, approved, and sent email
  waves.json              outreach batches
  interviews.json         proposed and confirmed interview times, outcomes
  research_runs.json      prospect research runs and their suggestions
  calls.json              index of calls; audio and transcripts live in calls/
  calls/<call-dir>/       the existing coach session layout (audio.wav, transcripts,
                          coach.jsonl, marks.jsonl, evidence.jsonl, session.json)
  activity.jsonl          append-only log, one event per line
  exports/                files written by Export
```

- Collections are JSON arrays of objects with stable string ids (`hyp_…`, `org_…`,
  `per_…`, `evi_…`, `msg_…`). Every object has `created_at` and `updated_at` (UTC
  ISO 8601).
- Writes go to a temporary file, are fsynced, then renamed over the old file, so a
  crash never leaves half a file. The previous version is kept in the hidden
  `.sidecar/` subfolder as `<name>.json.bak`.
- The engine is the only writer while the app runs. It reloads a file if it changes
  on disk (an external edit) and logs that it did.
- A daily copy of the whole folder minus audio goes to
  `~/Library/Application Support/Sidecar/backups/` (keep 14).
- **Export** writes `exports/<slug>-<date>.json` (every collection in one file, plus
  transcripts as text) and `exports/<slug>-<date>.md` (a readable digest:
  hypotheses with their evidence and quotes, people and stages, call summaries).
  Either file can be pasted or uploaded into another AI tool.

### 3.2 Records

| Record | Key fields |
|---|---|
| project | name, slug, coach (activity, keyterms), banned_phrases, email (sender name, footer_enabled false by default), sending (daily cap 30, window, spacing) |
| hypothesis | code (H1), statement, kind (`problem`, `solution`, `competing`), status (`open`, `supported`, `weakened`, `rejected`, `parked`), notes, history |
| organization | name, aliases, domain, website, segment, already_contacted (bool), sources, notes |
| person | name, first_name, organization_id, role, email, email_confidence, phone (public business only), website, background, why_useful, why_receptive, segment, segment_basis, sources, researched_on, time_zone, stage, next_action, next_action_due, priority, scores, do_not_contact, notes |
| message | person_id, wave_id, kind (`initial`, `follow_up`, `final`, `reply`), subject, body, status (`draft`, `approved`, `scheduled`, `sent`, `failed`, `skipped`), checks, gmail ids, scheduled_for, sent_at |
| interview | person_id, proposed_times (with time zones), confirmed_at, time_zone, method (phone, video), call details, completed (bool), call_id, outcome notes |
| evidence | call_id, person_id, organization_id, at_seconds, quote, note, type, **basis**, source, review_status, links (hypothesis_id, stance) |
| research_run | query, created_at, cost, suggestions (each a person record in waiting, with sources) |

Field values:

- **email_confidence:** `verified_direct`, `inferred_direct`, `generic`,
  `unavailable`. Inferred addresses are always shown as inferred.
- **segment:** one of the project's segments, read from the research brief's
  Segments list, or empty when not known. `segment_basis` holds the evidence for
  the classification.
- **scores** (shown separately, never combined): `information_value`,
  `receptiveness`, `contactability`, `segment_diversity`,
  `organizational_independence`, each `high`, `medium`, `low` with a one-line reason.
- **stage:** `discovered`, `researching`, `ready_for_review`, `approved`,
  `scheduled_to_send`, `sent`, `follow_up_due`, `replied`, `interested`,
  `scheduling`, `confirmed`, `completed`, `declined`, `unresponsive`,
  `do_not_contact`. Interested, confirmed, and completed are distinct; a positive
  reply never marks an interview as confirmed or completed.
- **evidence type:** `behavior`, `incident`, `opinion`, `capability_claim`,
  `artifact`, `segment`, `secondhand`.
- **evidence basis:** `statement` (what the person said), `observed` (behavior
  the researcher saw directly), `artifact` (a document or screen shown), `interpretation`
  (the researcher's reading). Interpretation never counts as strong evidence.

### 3.3 Evidence rules

- Evidence belongs to a person and, through them, an organization. A hypothesis
  shows counts of **independent organizations**, not just items, so two coworkers
  never look like two confirmations.
- The hypothesis page separates **behavior and incidents** (strong) from
  **opinions, capability claims, secondhand, and interpretation** (weak).
- Solution hypotheses never receive evidence automatically from problem evidence.
- Status is set only by the user. An interview happening never changes a
  hypothesis; the app shows tallies and never computes a verdict.

### 3.4 Duplicate prevention

- Organizations are tracked globally by name, aliases, and email domain. A new
  prospect whose organization already exists is flagged before review.
- One contact per organization per wave by default. A second person at a contacted
  organization needs an explicit override, a gap of at least two weeks, and a check
  that the email text differs from the coworker's.
- The outreach brief's already-contacted organizations and people are imported as
  `already_contacted` and never offered as fresh prospects.

## 4. Pages

The main window uses a three-column macOS layout: sidebar, content, and an optional
inspector. A project switcher sits at the top of the sidebar.

```
Sidebar
  [Project: Example study ▾]
  Today
  Inbox                      (count of items waiting for review)
  ─ Research
    Hypotheses
    Evidence
    Brief
  ─ Outreach
    Review queue             (count)
    Campaigns
    People
    Find prospects
  ─ Calls
    Calls
  Settings (bottom)
```

### 4.1 Today
One screen that answers "what needs me". Sections, each a short list with a count and
a link: emails waiting for approval, replies to triage, evidence to review, prospect
suggestions to review, calls today and this week, sending status (sent today against
the daily cap, next scheduled send, paused or not). A "New call" button opens the
call setup sheet.

### 4.2 Inbox
A single review list for everything except outgoing emails (those have their own
queue, 4.6). Segmented control: All, Evidence, Replies, Prospects.
- **Evidence** items from a call: quote, the coach's note, proposed hypotheses and
  stance, type. Accept, edit (change hypotheses, stance, type, note), or reject.
  "Open in call" jumps to that moment in the call review page.
- **Replies**: the reply text, the AI's suggested class (interested, not now,
  referral, not interested, out of office, unsubscribe request) and suggested stage
  move. Approve the move, pick another stage, or dismiss. "Unsubscribe request" adds
  the address to the suppression list when approved.
- **Prospects**: see 4.10.
Keyboard: `J`/`K` move, `A` accept, `E` edit, `R` reject.

### 4.3 Hypotheses
A list grouped by kind (problem hypotheses, then the solution hypothesis, then the
competing explanation). Each row: code, statement, status, and a compact tally:
supports / contradicts / mixed, and the number of independent organizations behind
them. Sort by code or by most recent evidence. Add, reorder, and edit inline.

### 4.4 Hypothesis detail
- Header: code, statement (editable), kind, status menu.
- Tally bar: counts by stance, split into strong (behavior, incident) and weak
  (opinion, capability claim, secondhand), plus independent organizations.
- Evidence list, grouped by stance, each item showing the quote, person,
  organization, date, type, and a link to the call moment.
- Notes (markdown) and a history of status changes.

### 4.5 Evidence
A table of all accepted evidence in the project. Columns: date, quote, person,
organization, type, hypotheses with stance, source. Filters: hypothesis, stance,
type, organization, source. Selecting a row opens it in the inspector for editing.

### 4.6 Review queue (outgoing email)
The dashboard for cold emails. A list of proposed messages on the left (person,
company, campaign, step), the selected draft in the middle, and an inspector with
the person's details, research notes, and checks on the right.
- Checks are shown plainly and do not block (section 5.2): template lines intact,
  no em dashes, no banned phrases, at most one
  optional sentence with its source, reading time, email confidence, no coworker
  in this wave, recipient not on the do-not-contact list, no existing thread.
- Actions: Approve (`A`), Edit (inline, `E`), Regenerate the optional sentence
  with a note (`G`), Remove the optional sentence, Skip (`S`). Checkboxes allow
  approving several drafts at once, and "Approve all passing" approves every draft
  in the current filter with no failed checks; both ask for a confirmation that
  names the count.
- Approved emails move to the schedule. The header shows today's sends against the
  cap and the next send time, with a Pause button.

### 4.7 Campaigns
A list of campaigns with status, people enrolled, sent, replied, scheduled, and
interviewed counts.

### 4.8 Campaign detail
- **Template**: the canonical email and follow-up text from the outreach brief,
  shown with its fields (`first_name`, `organization`, `optional_sentence`). Edits
  apply to new drafts only.
- **Cadence**: initial, first follow-up after 3 to 4 business days, optional phone
  call for high-priority contacts, final email about a week later, then stop.
  Follow-ups stop for a person when they reply, bounce, decline, or opt out.
- **People**: enrolled people with stage. Add from People or from a CSV.
- **Sending**: sender account, daily cap, send window and days, pacing.
- **Generate drafts**: creates step-1 drafts for selected people. They appear in
  the review queue. Follow-up drafts are generated when a step becomes due, and also
  wait for review.

### 4.9 People
A table of people (and their organizations) across the project: name, company, role,
segment, email confidence, stage, last interaction, next action, source. Filters by
stage, segment, and wave. A board view groups the same rows by stage. An Overview
tab shows the metrics of section 5.7 and upcoming follow-ups and interviews. Selecting a person opens the inspector; double-click
opens the person page: contact details, organization, the email thread, calls,
evidence they gave, referrals, notes, and do-not-contact.

### 4.10 Find prospects
Describe who to find (industry, role, size, region, any must-haves) and run a
search. Claude uses web search to propose people or companies, each with the public
sources it used and a one-line reason. Results land as suggestions: approve to add
to People (optionally straight into a campaign), or reject. No email address is
guessed; addresses come only from a cited public source or from CSV/manual entry.
Each run shows its cost.

### 4.11 Calls
A list of calls (upcoming and past): person, organization, date, duration, marks,
evidence accepted out of proposed. "New call" opens the setup sheet: person,
planned minutes, notes, preflight results, consent reminder, Start.

### 4.12 Live call window
The current coach screen, restyled to match the app: status bar, pinned result,
NOW cards, history, evidence, transcript. It opens as its own window so it can sit
next to anything else. Same keys: `M`, `Q`, `S`, `Esc`, End with confirmation.

### 4.13 Call review
After the call: audio player with a waveform and marks, the final transcript
(click a line to seek), coach cards and marks along the timeline, and the call's
proposed evidence with accept/edit/reject (the same actions as the Inbox).

### 4.14 Brief
The project's research brief as an editable markdown document. It is what the
coach and the email writer read. A short "rules" panel lists the banned phrases and
hypothesis wording the email checks use.

### 4.15 Settings
- Account: connect or disconnect Gmail, sender name, signature, physical address,
  unsubscribe wording.
- Sending defaults: daily cap, window, pacing, follow-up delays.
- AI: API keys (stored in Keychain), models per task, monthly spend so far.
- Audio: input device, preflight.
- Coach: activity level, keyterms per project.
- Data: database and audio location, export, open folder.

## 5. Email

### 5.1 Connection
Gmail through Google OAuth for installed apps (loopback redirect with PKCE). The
refresh token is stored in the Keychain. Scopes: `gmail.send` and `gmail.readonly`.
The Google Cloud project is the user's own, set to *In production* and left
unverified (see section 9).

### 5.2 Writing emails from the template
Emails follow the template in the outreach brief's Email section. The template is
filled, not rewritten. The example in `examples/outreach_brief.md`:

```
Subject: question about planning the daily bake

Hi {first_name},

My name is Alex, and I'm a student studying how small food businesses plan their
day. I came across {organization} and would like to hear how you decide what to bake.

{optional_sentence}

Would you have 15 minutes for a call sometime next week? I'm only here to learn.

Best,
Alex
```

- `{first_name}` and `{organization}` come from the person's record.
- `{optional_sentence}` is the only AI-written part. Claude proposes either nothing
  or one plain sentence, and only when a cited source gives a real reason. The
  sentence must quote or point to the source it relies on. When it is empty, its
  line is removed.
- Follow-ups use the brief's follow-up template, are never personalized, and go in
  the original thread.
- Checks run on every draft and are shown in the review queue: no em dashes; no
  phrase from the outreach brief's banned list; one optional sentence at most;
  reading time under the project's limit; template lines unchanged; recipient not on
  the do-not-contact list; email confidence shown (an inferred address needs an
  explicit confirmation); no coworker contacted in this wave; no existing thread.

### 5.3 Review and approval
The review queue lets the user read each draft and approve it individually, or
select several (or all passing drafts in the current filter) and approve them
together after a confirmation that names the count. Nothing is sent without an
approval.

### 5.4 Sending
- Only approved messages are scheduled. Default: at most 30 per day across the
  project, inside the send window, with random gaps of 3 to 9 minutes.
- Sends are timed for the recipient's business hours in their time zone when it is
  known.
- Before each send: recheck do-not-contact, recheck that no reply has arrived in the
  thread, recheck the stage. Any failed check skips the send and logs why.
- No footer by default. These are non-commercial research requests; the footer
  (postal address and opt-out line) is a project setting for outreach that becomes
  commercial.
- Sending runs only while the app is open and pauses during a live call. Missed
  windows are never sent in a catch-up burst.

### 5.5 Follow-ups and phone calls
- Cadence from the outreach brief: initial on day 0; first follow-up after 3 to 4
  business days; optional phone call a few days later for contacts the user marks
  high priority; final email about one week after the first follow-up; then the
  person becomes `unresponsive`.
- Each due follow-up is drafted into the review queue; it is never sent on its own.
- A phone call step is a task with the public business number, not an action the
  app performs. The app never schedules an email and a call for the same person on
  the same day.
- A decline or a request not to be contacted moves the person to `declined` or
  `do_not_contact` once approved, and stops everything for them.

### 5.6 Replies and scheduling
The engine polls Gmail for new messages in tracked threads. Each reply becomes an
Inbox item with a suggested class (interested, proposing times, confirmed, not now,
declined, do not contact, referral, out of office, bounce) and suggested stage.
Nothing changes until the user approves. Any reply pauses that person's follow-ups
immediately.

Scheduling keeps proposed times and confirmed times separate, always with a time
zone. Only an explicit confirmation moves a person to `confirmed`. After the call,
marking the interview completed links the call, the person, and the organization to
the evidence from that call.

### 5.7 Metrics
An Outreach overview shows: emails sent, replies, positive replies, interviews
confirmed, interviews completed, response rate by segment, completed interviews by
independent organization, follow-ups due, and source diversity (segments and
organizations represented). No open or click tracking.

## 6. Prospect research

A research run sends the target description, the outreach brief, and the list of
known organizations to Claude with web search. Each suggestion is a person record
waiting for review, with: name, company, role, email and its confidence, public
business phone, website, background, why useful, why receptive, segment with its
basis, the five separate scores with reasons, sources (URL, title, quoted text),
and the research date.

Rules, from the outreach brief and the law:
- Public business information only, from first-party or credible sources (company
  sites, staff bios, association directories, public professional profiles). No
  scraping of sites whose terms forbid it.
- Never guess an email and call it verified. Pattern-based guesses are marked
  `inferred_direct` and need confirmation before sending.
- Facts and inferences are kept apart: why_receptive is labeled as an inference.
- Already-contacted organizations are excluded; one suggestion per organization.
- Each run asks for a mix that includes counterexample segments named in the
  research brief.
- Default limit 12 suggestions per run. Cost is shown before and after.

## 7. Calls and the coach

The live call engine is the existing `coach` package. Changes:
- The coach reads the project's brief, hypotheses (rendered with their codes), and
  activity level from the database instead of files.
- The call is linked to a person; their name, organization, and notes fill the
  session header. Previous calls with the same person are summarized in one short
  paragraph in the brief block.
- Evidence the coach logs during the call becomes `proposed` evidence linked to the
  call, the person, and the hypothesis codes it named.
- After the batch transcript, one additional Claude pass proposes evidence the live
  coach missed. It runs by default after every call. Its items also go to the review
  inbox.
- Session files stay in a folder per call, as today, so `coach recover` and
  `coach finalize` keep working.

## 8. Architecture

```
┌──────────────────────────── Sidecar.app (Tauri v2) ───────────────────────────┐
│  Rust shell: windows, native menus, shortcuts, Keychain access,                 │
│  starts and stops the engine sidecar, passes it a port and a session token      │
│                                                                                 │
│  Web UI (TypeScript, Svelte, Vite)  ◀── HTTP + WebSocket on 127.0.0.1 ──┐       │
└──────────────────────────────────────────────────────────────────────────┼──────┘
                                                                           │
┌──────────────────────── Engine sidecar (Python 3.14) ────────────────────┴──────┐
│  FastAPI app                                                                    │
│   ├── api/ projects, hypotheses, evidence, people, campaigns, review, settings  │
│   ├── coach/   existing live call pipeline (audio, STT, scheduler, LLM)         │
│   ├── mail/    Gmail client, scheduler, reply poller, suppression               │
│   ├── writer/  email generation and checks                                      │
│   ├── research/ prospect research runs                                          │
│   └── store/   project folder: JSON collections, atomic writes, export                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Why Tauri plus a Python engine:** the call pipeline is proven in Python and
  depends on sounddevice, numpy, and the async Deepgram and Anthropic clients.
  Rewriting it in Rust adds risk for no user benefit. Tauri gives a native window,
  menus, Keychain, and a signed app bundle; the engine keeps doing the heavy work.
- **UI framework:** Svelte with TypeScript. Small output, no virtual DOM, and plain
  CSS, built with Vite, which Tauri expects anyway.
- **Engine lifecycle:** the Rust shell starts the engine at launch with a random
  port and a random token, waits for its health check, and stops it on quit. The UI
  sends the token on every request. The engine binds to 127.0.0.1 only.
- **Live call isolation:** the live call keeps its own threads and supervised tasks.
  Mail sending and reply polling pause during a live call so the call has the
  network and CPU to itself.
- **Storage:** the project folder of section 3.1. Each collection is loaded into
  memory at startup (hundreds of records, small) and written back atomically on
  every change.
- **Secrets:** Anthropic key, Deepgram key, and Gmail refresh token in the Keychain
  (through the engine's `keyring` package), never in the database or logs.
- **Packaging:** the engine is built into a single executable and bundled as a
  Tauri sidecar. The app needs microphone permission; the usage description names
  the call recorder.

## 9. Verified platform facts

Checked against official documentation on 2026-10-07. Items marked *(test)* are
behavior Apple or Google do not guarantee and must be confirmed on this Mac.

**Tauri and the engine sidecar**
- The engine is bundled with `bundle.externalBin`; the file name ends in the target
  triple (`engine-aarch64-apple-darwin`). Spawning it needs the shell plugin with a
  `shell:allow-spawn` capability scoped to that one sidecar.
- A sidecar spawned from Rust is not killed automatically on quit. The shell keeps
  the child handle and kills it on exit, and the engine also exits on its own when
  its parent process disappears (stdin closed or parent PID changed). Build the
  engine as a PyInstaller *onedir* bundle so no orphaned second process can remain.
- The web UI reaches the engine with plain `fetch` and `WebSocket` to 127.0.0.1;
  no capability is needed. If a CSP is set it must list the engine's address under
  `connect-src`. The engine allows CORS only from the Tauri origin and requires the
  per-launch token.
- Microphone: `NSMicrophoneUsageDescription` in the app's Info.plist and the
  `com.apple.security.device.audio-input` entitlement. macOS attributes a child
  process's microphone use to the parent app while the parent is running *(test)*.
  Sign with a stable identity (a free Apple Development certificate is enough);
  ad-hoc signatures change on every build and can reset the permission.
- Native look: `titleBarStyle: "Overlay"` with `hiddenTitle`, traffic lights placed
  over the sidebar, and the `sidebar` window effect for the translucent sidebar
  (needs `transparent: true` and `macOSPrivateApi`, which is fine outside the App
  Store). App menus are built with the menu API; app shortcuts are menu
  accelerators, not global shortcuts.
- Secrets: the engine stores keys and the Gmail refresh token with the Python
  `keyring` package, which uses the macOS Keychain. No Stronghold vault.
- Personal use needs no notarization: a locally built app is not quarantined. No
  auto-updater in v1.

**Gmail**
- OAuth: installed-app loopback flow with PKCE. Scopes: `gmail.send` (sensitive) and
  `gmail.readonly` (restricted). `gmail.modify` only if labeling is added later.
- A Google Cloud project in *Testing* status expires refresh tokens after 7 days.
  The project is set to *In production* and left unverified, which is allowed for
  personal use (under 100 users, accepting the "unverified app" screen once). With
  a Workspace account, an *Internal* app avoids this too.
- Limits: consumer Gmail about 500 messages per day; paid Workspace 2,000 per day
  (500 on trial accounts). The app's own default cap (30 per day) stays far below.
- API cost per user: `messages.send` 100 units, `history.list` 2 units, against
  6,000 units per minute. Polling is cheap.
- Replies: store each sent message's `threadId` and RFC `Message-ID`. Follow-ups use
  the same `threadId` with `In-Reply-To` and `References`. Poll `history.list` every
  2 minutes from the last `historyId`; on a 404, run a full resync. Detect bounces
  (mailer-daemon) and auto-replies (`Auto-Submitted`, `X-Autoreply` headers).
- Google's bulk-sender rules start at 5,000 messages per day, far above this app.
  With a custom domain, SPF, DKIM, and DMARC should still be set up.

**Compliance**
- CAN-SPAM covers *commercial* email (advertising a product or service) and has no
  business-to-business exemption for it: truthful headers, the sender's postal
  address, and a working opt-out. Sidecar's research requests are not commercial,
  so the footer is off by default; truthful headers and honoring every decline
  apply regardless. The do-not-contact list is permanent and checked before every
  send.
- Recipients in the EU, UK, or Canada bring GDPR, PECR, or CASL rules (a documented
  legitimate interest or implied consent, sender identification, opt-out). v1 flags
  any recipient whose domain or location suggests one of these regions so the user
  can decide.
- Prospect research never generates addresses by guessing patterns (treated as an
  aggravated violation under CAN-SPAM) and never scrapes sites whose terms forbid
  it, such as LinkedIn. Only published business contact details with a cited
  source are used.

## 10. Design language

- macOS Human Interface Guidelines. System font (SF Pro), system colors, light and
  dark appearance.
- Layout: translucent sidebar, unified toolbar, content area, optional inspector.
- Type scale: Large title 26, title 20, headline 13 semibold, body 13, callout 12,
  caption 11.
- Color: one accent (the orange from the logo). Status colors only where they carry meaning
  (green supports, red contradicts, orange mixed or warning), always with a text
  label so color is never the only signal.
- Components: native-style source list, tables with sortable headers, segmented
  controls, popup buttons, sheets for multi-step actions, inspectors for details.
- No gradients, illustrations, glassy cards, emoji, decorative icons, sparkle or
  "AI" icons, or marketing-style hero sections. Generated content is labeled with
  the word "Draft" or "Suggested", not a special visual treatment.
- Density: comfortable table rows (28 px), 8 px spacing grid. Controls use macOS
  sizes (24-30 px tall) because the app is pointer-driven.
- The live call window uses dark appearance so it stays calm next to a call.
- Page designs: the Sidecar design canvas (one clickable artboard per page in
  section 4, sharing one sidebar component).

## 11. Migration

- The existing `coach` CLI keeps working during the transition.
- `sidecar new` creates a project from a research brief and an optional outreach
  brief: hypotheses and the competing explanation from the research brief, and
  from the outreach brief the already-contacted organizations, people already
  emailed, drafted prospects (as `ready_for_review`), and interview leads (as
  `interested`, with a next action to confirm the real date rather than assume it).
- An importer reads coach session folders from the recordings directory into calls, and their evidence
  as proposed evidence for review.

## 12. Milestones

1. **Shell and store.** Tauri app with sidebar navigation, engine sidecar lifecycle,
   the project folder store with export, seeding from both briefs, and the
   Hypotheses, Evidence, People, and Brief pages.
2. **Calls inside the app.** Call setup sheet, live call window, call library, call
   review, evidence proposals, Inbox evidence review, importer for old sessions.
3. **Hypotheses and evidence.** Hypothesis list and detail with tallies and
   independence counts, Evidence table.
4. **Gmail.** OAuth connect, send one approved test email to yourself, reply poller,
   suppression list.
5. **Campaigns and review queue.** Outline editor, sequences, draft generation with
   checks, review queue, paced sending, follow-up proposals.
6. **Replies.** Reply classification suggestions and pipeline moves in the Inbox.
7. **Find prospects.** Research runs with sources and the suggestion review flow,
   CSV import with column mapping.
8. **Polish.** Today page, keyboard shortcuts everywhere, menus, backups, export.

Each milestone ships something usable and keeps the live call path working.

Built so far (2026-10-08): milestone 1; the session importer from milestone 2
(command line); Inbox review and milestone 3; draft generation with checks and the
review queue from milestone 5, without campaigns, sequences, or sending; CSV import
from milestone 7; and from milestone 8 the Today page, daily backups, and export.
Organizations have their own page, and interviews are recorded on each person.
Calls start from the app: the engine runs the coach as a child process with the
project's brief, prompts, and keyterms, the shell opens its page in a call window,
and the session is imported when the coach exits. The call library and live call
window from milestone 2 are in, and so is call review. Milestone 4 and the sending
half of milestone 5 are built: Gmail OAuth with PKCE (token in the Keychain),
paced sending with rechecks, reply detection through the history API, reply
triage and responses in the Inbox, and follow-up drafts. Prospect research from
milestone 7 is built. Not built: campaigns and sequences as their own pages, reply
classification suggestions, and the post-call missed-evidence pass.

## 13. Decisions

1. Daily cap 30, spaced 3 to 9 minutes apart. Approved.
2. Emails can be approved one at a time or in bulk after reading. Approved.
3. No postal-address footer: the emails are non-commercial research requests. The
   footer stays available as a setting.
4. The post-call missed-evidence pass runs by default.
5. Storage is a portable project folder with a one-click export (section 3.1).
