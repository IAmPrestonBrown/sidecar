export const STAGES: [string, string][] = [
  ['discovered', 'Discovered'],
  ['researching', 'Researching'],
  ['ready_for_review', 'Ready for review'],
  ['approved', 'Approved'],
  ['scheduled_to_send', 'Scheduled to send'],
  ['sent', 'Sent'],
  ['follow_up_due', 'Follow-up due'],
  ['replied', 'Replied'],
  ['interested', 'Interested'],
  ['scheduling', 'Scheduling'],
  ['confirmed', 'Confirmed'],
  ['completed', 'Completed'],
  ['declined', 'Declined'],
  ['unresponsive', 'Unresponsive'],
  ['do_not_contact', 'Do not contact'],
]

export const EMAIL_CONFIDENCE: [string, string][] = [
  ['verified_direct', 'Verified direct'],
  ['inferred_direct', 'Inferred direct'],
  ['generic', 'Generic'],
  ['unavailable', 'Unavailable'],
]

export const EVIDENCE_TYPES: [string, string][] = [
  ['behavior', 'Behavior'],
  ['incident', 'Incident'],
  ['opinion', 'Opinion'],
  ['capability_claim', 'Capability claim'],
  ['artifact', 'Artifact'],
  ['segment', 'Segment'],
  ['secondhand', 'Secondhand'],
]

export const EVIDENCE_BASIS: [string, string][] = [
  ['statement', 'Their statement'],
  ['observed', 'Observed directly'],
  ['artifact', 'Artifact shown'],
  ['interpretation', 'My interpretation'],
]

export const HYPOTHESIS_STATUS: [string, string][] = [
  ['open', 'Open'],
  ['supported', 'Supported'],
  ['weakened', 'Weakened'],
  ['rejected', 'Rejected'],
  ['parked', 'Parked'],
]

export const STANCES: [string, string][] = [
  ['supports', 'Supports'],
  ['contradicts', 'Contradicts'],
  ['mixed', 'Mixed'],
]

export const SCORE_DIMENSIONS: [string, string][] = [
  ['information_value', 'Information value'],
  ['receptiveness', 'Receptiveness'],
  ['contactability', 'Contactability'],
  ['segment_diversity', 'Segment diversity'],
  ['organizational_independence', 'Organizational independence'],
]

const maps = [STAGES, EMAIL_CONFIDENCE, EVIDENCE_TYPES, EVIDENCE_BASIS, HYPOTHESIS_STATUS, STANCES]
const lookup = new Map<string, string>()
for (const list of maps) for (const [k, v] of list) if (!lookup.has(k)) lookup.set(k, v)

/** Human label for any stored enum value. */
export function label(value: string): string {
  return lookup.get(value) ?? value.replace(/_/g, ' ')
}

export const STRONG_TYPES = new Set(['behavior', 'incident'])

export function isStrong(type: string, basis: string): boolean {
  return STRONG_TYPES.has(type) && basis !== 'interpretation'
}

export function shortDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function mmss(seconds: number | null): string {
  if (seconds == null) return ''
  const s = Math.max(0, Math.floor(seconds))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
