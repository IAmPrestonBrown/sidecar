export type Level = 'high' | 'medium' | 'low'
export type Stance = 'supports' | 'contradicts' | 'mixed'

export interface Source {
  url: string
  title: string
  quote: string
}

export interface Rec {
  id: string
  created_at: string
  updated_at: string
}

export interface Hypothesis extends Rec {
  code: string
  title: string
  statement: string
  kind: 'problem' | 'solution' | 'competing'
  status: 'open' | 'supported' | 'weakened' | 'rejected' | 'parked'
  notes: string
  sort: number
  history: { at: string; text: string }[]
}

export interface Organization extends Rec {
  name: string
  aliases: string[]
  domain: string
  website: string
  segment: string
  already_contacted: boolean
  independent: boolean
  sources: Source[]
  notes: string
}

export interface Score {
  level: Level
  reason: string
}

export interface Person extends Rec {
  name: string
  first_name: string
  organization_id: string
  role: string
  email: string
  email_confidence: string
  phone: string
  website: string
  background: string
  why_useful: string
  why_receptive: string
  segment: string
  segment_basis: string
  sources: Source[]
  researched_on: string
  time_zone: string
  stage: string
  next_action: string
  next_action_due: string
  priority: Level
  scores: Record<string, Score | null>
  do_not_contact: boolean
  notes: string
}

export interface Evidence extends Rec {
  call_id: string
  person_id: string
  organization_id: string
  at_seconds: number | null
  quote: string
  note: string
  type: string
  basis: string
  source: string
  review_status: 'proposed' | 'accepted' | 'rejected'
  links: { hypothesis_id: string; stance: Stance; strength?: '' | 'strong' | 'moderate' | 'weak' }[]
  // Present on evidence imported from a research spreadsheet.
  source_title?: string
  source_url?: string
  context?: string
  codings?: {
    hypothesis: string
    direction: string
    strength: string
    rationale: string
    alternative: string
  }[]
}

export interface Tally {
  supports: { strong: number; weak: number }
  contradicts: { strong: number; weak: number }
  mixed: { strong: number; weak: number }
  organizations: number
}

export interface ProjectMeta {
  name: string
  slug: string
  path: string
  coach: { activity: string; keyterms: string[] }
  email: EmailSettings
  sending: {
    active: boolean
    daily_cap: number
    window_start: string
    window_end: string
    weekdays: number[]
    min_gap_minutes: number
    max_gap_minutes: number
  }
  banned_phrases: string[]
  segments: string[]
}

export interface ProjectSummary {
  slug: string
  name: string
  path: string
}

export interface Overview {
  stages: Record<string, number>
  people: number
  organizations: number
  evidence_to_review: number
  evidence_accepted: number
  drafts_to_review: number
  replies_to_review: number
  sent: number
  prospects_to_review: number
  leads_open: Person[]
  interviews: unknown[]
}

export interface EmailSettings {
  sender_name: string
  footer_enabled: boolean
  postal_address: string
  opt_out_line: string
  subject_template: string
  body_template: string
  follow_up_template: string
  final_template: string
  max_reading_seconds: number
}

export interface Check {
  name: string
  level: 'pass' | 'warn' | 'fail'
  detail: string
}

export interface Message extends Rec {
  person_id: string
  wave_id: string
  kind: 'initial' | 'follow_up' | 'final' | 'reply' | 'response'
  subject: string
  body: string
  status: 'draft' | 'approved' | 'scheduled' | 'sent' | 'failed' | 'skipped' | 'received'
  checks: Check[]
  gmail_thread_id: string
  sent_at: string
  error: string
  from_address: string
  received_at: string
  auto_reply: boolean
  bounce: boolean
  triaged: boolean
}

export interface QueueItem extends Message {
  person: Person | null
  organization: Organization | null
}

export interface Interview extends Rec {
  person_id: string
  proposed_times: string[]
  time_zone: string
  confirmed_time: string
  method: '' | 'phone' | 'video' | 'in_person'
  details: string
  completed: boolean
  call_id: string
  outcome: string
}

export interface SegmentCounts {
  contacted: number
  replied: number
  positive: number
  completed: number
}

export interface OutreachMetrics {
  emails_sent: number
  drafts: number
  approved_waiting: number
  contacted: number
  replied: number
  positive: number
  confirmed: number
  completed: number
  completed_organizations: string[]
  by_segment: Record<string, SegmentCounts>
  follow_ups_due: { id: string; name: string; next_action: string; due: string }[]
  segments_completed: string[]
}

export interface ImportRow {
  line: number
  values: Record<string, string>
  action: 'create' | 'skip'
  issues: string[]
}

export interface ImportPreview {
  headers: string[]
  mapping: Record<string, string>
  targets: string[]
  rows: ImportRow[]
}

export interface Call extends Rec {
  person_id: string
  title: string
  started_at: string
  duration_s: number
  session_dir: string
  status: 'planned' | 'recording' | 'finalizing' | 'done' | 'imported'
  planned_minutes: number
  marks: number
  cost_usd: number
}

export interface ActiveCall {
  slug: string
  person_id: string
  person_name: string
  started_at: string
  state: 'starting' | 'ready' | 'ending' | 'ended' | 'failed'
  url: string
  session_dir: string
  call_id: string
  error: string
  output: string[]
}

export interface GmailStatus {
  configured: boolean
  client_file: string
  connected: boolean
  email: string
  connecting: boolean
}

export interface SendingStatus {
  active: boolean
  connected: boolean
  sent_today: number
  daily_cap: number
  waiting: number
  blocked: string
  next_after: string
  last_error: string
}

export interface CallReview {
  segments: { start: number; end: number; label: string; text: string }[]
  transcript_source: 'final' | 'live' | 'none'
  marks: { at: number; headline: string; claim: string; unknown: string; ask: string }[]
  asks: { at: number; ask: string }[]
  has_audio: boolean
  duration_s: number
  labels: Record<string, string>
}
