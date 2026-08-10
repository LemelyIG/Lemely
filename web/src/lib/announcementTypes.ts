/*
 * Wire types for S-28's two halves, mirroring
 * `lemely/web/schemas_announcements_student.py` and
 * `lemely/web/schemas_exam_calendar.py` field for field.
 *
 * The `availability` unions are the load-bearing part of the calendar contract
 * (D5.8), not metadata. The `exam_dates` table ships empty in every environment
 * this build produces, so the screen's job is to say *why* it has nothing —
 * "finish onboarding" and "we do not hold the official timetable yet" are
 * different sentences owed to different students, and one blank panel can
 * express neither. Do not collapse these into a boolean.
 */

/** Which audience carried an announcement to this reader. */
export type AnnouncementScope = "class" | "school"

export interface StudentAnnouncement {
  announcementId: string
  scope: AnnouncementScope
  classId: string | null
  schoolId: string | null
  title: string
  body: string
  /**
   * The **effective** publication time (`publish_at` when scheduled, else
   * `created_at`) and the key the server orders by. It is the only time field
   * on the wire on purpose: sorting by anything else here would silently
   * disagree with the server's ordering.
   */
  publishedAt: string
  /** When this student first opened it. `null` means unread — an absence of a
   * receipt row, never a flag, so there is no `isRead` boolean to drift. */
  readAt: string | null
  authorId: string
}

export interface StudentAnnouncementsPage {
  announcements: StudentAnnouncement[]
}

export interface UnreadAnnouncementCount {
  unreadCount: number
}

export interface AnnouncementReadReceipt {
  announcementId: string
  /** On a re-open this is the *original* first read, not the current instant —
   * the endpoint is idempotent and stores first-read only. */
  readAt: string
}

/* ── Exam calendar ──────────────────────────────────────────────────────── */

export interface ExamDate {
  paperVariant: string
  examDate: string
  /** Local start time exactly as the timetable prints it. `null` when it does
   * not state one — never defaulted to midnight, because a missing time must
   * read as missing. */
  startsAtLocal: string | null
  durationMinutes: number | null
  /** Which published timetable this date came from. On the wire so a student
   * who thinks a date is wrong can name the document rather than argue with
   * the app. */
  source: string
}

/**
 * Why one paper's `dates` list looks the way it does.
 *
 * `no_session` is the *student's* gap — they have not said which session they
 * are sitting, and they can fix it in onboarding. `no_timetable` is the
 * *platform's* gap — they named a session and we hold no official dates for
 * it. Presenting the first as the second blames Cambridge for a blank the
 * student can fill in themselves (D5.8).
 */
export type ExamEntryAvailability = "dated" | "no_timetable" | "no_session"

export interface StudentExamEntry {
  subjectCode: string
  sessionMonth: string | null
  sessionYear: number | null
  paperNumber: number
  availability: ExamEntryAvailability
  /** A list, not a single date: the timetable's grain is the *variant* and the
   * student declares only a paper number, so "Paper 2" can legitimately map to
   * several variants on different days. Picking the earliest would invent the
   * one fact the student never gave us. */
  dates: ExamDate[]
}

/** Top-level cause when the calendar as a whole has nothing to show. */
export type ExamCalendarAvailability = "available" | "no_enrolment" | "no_timetable"

export interface StudentExamCalendar {
  availability: ExamCalendarAvailability
  entries: StudentExamEntry[]
}
