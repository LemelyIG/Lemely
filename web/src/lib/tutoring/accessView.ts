/*
 * T23 · what S-38 (Tutors & your data) says, as pure functions (SPEC §d S-38,
 * §i.8). The five sections are: who you share with, who looked, which classes'
 * teachers see you, whether your grades count, which tutors you blocked.
 *
 * ── Masking (SC-11, SPEC §i.8) ──────────────────────────────────────────────
 *
 * A student never learns that a tutor blocked them, was suspended or was
 * closed. The API already sends `tutor_unavailable` for all three; the types
 * still list `tutor_suspended` and `tutor_closed`, so the status table below
 * gives them the same view as `tutor_unavailable`, by reference. There is no
 * client branch on them anywhere else. `blocked` is the student's own block
 * (the API sends it only when the student's block explains the ending).
 *
 * Fixed sentences are copied from the SPEC and parsed back out of it by
 * `tutoringAccessView.test.ts`. Names (tutor, class, teacher) are returned as
 * given and drawn as plain text.
 *
 * Parent reuse: `accessLogView` takes the child's name and the link base so
 * P-08 shows the same log in the third person.
 */

import type {
  AccessLogEntry,
  Block,
  ClassAccessItem,
  Grant,
  GrantStatus,
  TutoringSettings,
  TutoringSettingsUpdate,
} from "@/lib/tutoringTypes"
import { formatTutorDate, SESSION_ZONE, SESSION_ZONE_LABEL } from "./sessionView"
import { formatTutorInstant } from "./slotGroups"

// ── Section 1 · sharing ────────────────────────────────────────────────────

export const SHARING_EXPLAINER =
  "Your grades, predicted grades, target grades, papers' marks, weak topics, trend, at-risk warnings and the days you were active, for all subjects. Never your answer sheets, and never the time of day you used Lemely."
export const SHARING_PARENTS_LINE =
  "Your linked parents can see who you share with and each time a tutor looked."
export const EMPTY_GRANTS_LINE = "You aren't sharing your progress with any tutor."
export const EMPTY_LOG_LINE = "No tutor has looked at your progress."

export type GrantStatusIcon = "ShareNetwork" | "StopCircle" | "Hourglass" | "ProhibitInset" | "UserMinus"
export type GrantTone = "ok" | "neutral" | "warn"

export interface GrantStatusView {
  label: string
  detail: string
  icon: GrantStatusIcon
  tone: GrantTone
  /** Only a live grant can be stopped. */
  live: boolean
}

const TUTOR_SIDE_ENDING: GrantStatusView = {
  label: "Sharing ended",
  detail: "They can't see your progress through Lemely's tutoring pages.",
  icon: "UserMinus",
  tone: "neutral",
  live: false,
}

/**
 * Every status the API can send. `tutor_suspended` and `tutor_closed` are the
 * very same object as `tutor_unavailable`: a tutor-side ending reads one way
 * whatever caused it.
 */
export const GRANT_STATUS_VIEW: Record<GrantStatus, GrantStatusView> = {
  active: {
    label: "Sharing",
    detail: "This tutor can see your progress through Lemely's tutoring pages.",
    icon: "ShareNetwork",
    tone: "ok",
    live: true,
  },
  revoked: {
    label: "You stopped sharing",
    detail: "They can't see your progress through Lemely's tutoring pages.",
    icon: "StopCircle",
    tone: "neutral",
    live: false,
  },
  expired: {
    label: "Sharing expired",
    detail: "They can't see your progress through Lemely's tutoring pages.",
    icon: "Hourglass",
    tone: "neutral",
    live: false,
  },
  blocked: {
    label: "You blocked this tutor",
    detail: "Sharing ended when you blocked them.",
    icon: "ProhibitInset",
    tone: "neutral",
    live: false,
  },
  tutor_unavailable: TUTOR_SIDE_ENDING,
  tutor_suspended: TUTOR_SIDE_ENDING,
  tutor_closed: TUTOR_SIDE_ENDING,
}

export interface GrantRowView {
  grantId: string
  tutorName: string
  tutorHref: string
  sinceLine: string
  status: GrantStatusView
  canStop: boolean
  stopLabel: string
}

export function grantRowView(grant: Grant): GrantRowView {
  const status = GRANT_STATUS_VIEW[grant.status]
  const since = `Since ${formatTutorDate(grant.createdAt)}`
  const ended = grant.revokedAt !== null && !status.live ? `, ended ${formatTutorDate(grant.revokedAt)}` : ""
  return {
    grantId: grant.grantId,
    tutorName: grant.tutor.publicName,
    tutorHref: `/student/tutors/${encodeURIComponent(grant.tutor.tutorId)}`,
    sinceLine: `${since}${ended}`,
    status,
    canStop: status.live,
    stopLabel: `Stop sharing with ${grant.tutor.publicName}`,
  }
}

/** Live grants and ended ones, each in the API's order (live first, newest first). */
export function splitGrants(grants: readonly Grant[]): { live: Grant[]; ended: Grant[] } {
  const live: Grant[] = []
  const ended: Grant[] = []
  for (const grant of grants) (GRANT_STATUS_VIEW[grant.status].live ? live : ended).push(grant)
  return { live, ended }
}

export interface StopSharingCopy {
  title: string
  /** In order: what stops, which class still shows progress (only when there is one), what still counts. */
  lines: string[]
  confirmLabel: string
  cancelLabel: string
}

function listNames(names: readonly string[]): string {
  if (names.length <= 1) return names.join("")
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`
}

/**
 * The stop-sharing sheet. The class line appears only when the tutor also
 * teaches one of the student's classes (`alsoTeachesClasses`): sharing ends,
 * the class roster does not, and the sheet must not promise otherwise.
 */
export function stopSharingCopy(grant: Pick<Grant, "tutor" | "alsoTeachesClasses">): StopSharingCopy {
  const lines = ["They can't see your progress through Lemely's tutoring pages from now on."]
  const classes = grant.alsoTeachesClasses
  if (classes.length > 0) {
    lines.push(
      `This tutor also teaches your ${classes.length === 1 ? "class" : "classes"} ${listNames(classes)}, so they still see your class progress there.`,
    )
  }
  lines.push("Your grades are still counted in their results unless you turn that off below.")
  return {
    title: `Stop sharing with ${grant.tutor.publicName}?`,
    lines,
    confirmLabel: "Stop sharing",
    cancelLabel: "Keep sharing",
  }
}

// ── Section 2 · who looked ─────────────────────────────────────────────────

export interface AccessLogView {
  tutorName: string
  /** The tutor's page, or null when the entry carries no profile id. */
  tutorHref: string | null
  action: string
  timeLabel: string
}

/**
 * One line of the audit log. Without `childName` it is the student's own
 * ("viewed your progress"); with it, a parent's ("viewed Maya's progress").
 */
export function accessLogView(
  entry: AccessLogEntry,
  childName?: string,
  tutorBase = "/student/tutors",
): AccessLogView {
  const detail = entry.action === "detail"
  const action =
    childName === undefined
      ? detail
        ? "viewed your progress"
        : "saw you in their student list"
      : detail
        ? `viewed ${childName}'s progress`
        : `saw ${childName} in their student list`
  return {
    tutorName: entry.tutorName,
    tutorHref: entry.tutorId === null ? null : `${tutorBase}/${encodeURIComponent(entry.tutorId)}`,
    action,
    timeLabel: formatTutorInstant(entry.accessedAt, SESSION_ZONE, SESSION_ZONE_LABEL),
  }
}

// ── Section 3 · classes whose teacher sees you ─────────────────────────────

export const ASK_SCHOOL_LINE = "To leave this class, ask your school."

export interface ClassAccessView {
  classId: string
  className: string
  teacherName: string
  /** The school's name, or "Independent class". */
  whereLine: string
  canLeave: boolean
  askSchool: boolean
  /** The class teacher is also a tutor this student shares with or has booked. */
  alsoTutor: boolean
}

export function classAccessView(item: ClassAccessItem): ClassAccessView {
  return {
    classId: item.classId,
    className: item.className,
    teacherName: item.teacherName,
    whereLine: item.schoolName ?? "Independent class",
    canLeave: item.leavable,
    askSchool: !item.leavable,
    alsoTutor: item.teacherIsYourTutor,
  }
}

export interface LeaveClassCopy {
  title: string
  body: string
  confirmLabel: string
  cancelLabel: string
}

export function leaveClassCopy(item: Pick<ClassAccessItem, "className">): LeaveClassCopy {
  return {
    title: `Leave ${item.className}?`,
    body: `You'll leave ${item.className}. The teacher won't see your progress through this class any more.`,
    confirmLabel: "Leave class",
    cancelLabel: "Stay in class",
  }
}

// ── Section 4 · results counting ───────────────────────────────────────────

export const COUNTING_LABEL = "Count my grades in my tutors' results"
export const COUNTING_EXPLAINER =
  "Turning this off removes you from every tutor's results. When anyone's choice changes, that tutor's results are hidden for 90 days so no one can work out a grade from the change."

/** The box is ticked while the student has not opted out. */
export function countingChecked(settings: Pick<TutoringSettings, "outcomeStatsOptOut">): boolean {
  return !settings.outcomeStatsOptOut
}

export function countingUpdate(checked: boolean): TutoringSettingsUpdate {
  return { outcomeStatsOptOut: !checked }
}

// ── Section 5 · blocked tutors ─────────────────────────────────────────────

export const EMPTY_BLOCKS_LINE = "You haven't blocked any tutors."
export const UNBLOCK_NOTE = "Unblocking doesn't bring back sharing or cancelled sessions."

export interface BlockRowView {
  counterpartId: string
  name: string
  sinceLine: string
  unblockLabel: string
}

export interface UnblockSheetCopy {
  title: string
  consequence: string
  confirmLabel: string
  pendingLabel: string
  cancelLabel: string
}

/** The sheet before Unblock acts: what it does not undo is said before the button. */
export function unblockSheetCopy(block: Pick<Block, "displayName">): UnblockSheetCopy {
  return {
    title: `Unblock ${block.displayName}?`,
    consequence: UNBLOCK_NOTE,
    confirmLabel: "Unblock",
    pendingLabel: "Unblocking",
    cancelLabel: "Keep blocked",
  }
}

export function blockRowView(block: Block): BlockRowView {
  return {
    counterpartId: block.counterpartId,
    name: block.displayName,
    sinceLine: `Blocked ${formatTutorDate(block.createdAt)}`,
    unblockLabel: `Unblock ${block.displayName}`,
  }
}
