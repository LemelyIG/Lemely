import type { WaitlistApplicant, WaitlistBoard, WaitlistLevel, WaitlistRole } from "@/lib/waitlist-api"
import type { WaitlistStatus } from "@/lib/waitlist-api"
/* Clearly fake seed rows for the admin queue preview. Every email is @example.com. */


/* Clearly fake names; the oldest row has none, as rows from before the field existed do. */
const NAMES: (string | null)[] = ["Sample Student One", "Teacher Example", "Partial Applicant", "Parent Example", "Example Centre Lead", "Sample Student Two", "Declined Example", "Teacher Sample", "Partial Two", "Parent Sample", "Centre Example Two", "Student Example Three", "Teacher Example Two", "Sample Student Four", "Parent Example Two", "Student Example Five", "Partial Three", "Teacher Example Three", "Student Sample Six", "Centre Sample Three", "Student Example Seven", "Parent Example Three", "Student Sample Eight", "Teacher Example Four", null]
const CONSENT = "Applying opts you in to Lemely emails."
type Raw = { role: string; levels: string[]; subjects: string[]; other?: string; boards: string[]; session: string; phone?: string; whatsapp?: boolean; centre?: string; status: WaitlistStatus; partial: boolean; note: string; created: string; source: string }
const rows: Raw[] = [
  { role: "student", levels: ["IGCSE"], subjects: ["Biology", "Chemistry", "Physics"], boards: ["CAIE"], session: "May/June 2027", phone: "+20 100 000 0001", whatsapp: true, status: "new", partial: false, note: "", created: "2026-11-08T07:41:00Z", source: "waitlist_share" },
  { role: "teacher", levels: ["IGCSE", "A-Level"], subjects: ["Mathematics"], boards: ["CAIE", "Edexcel"], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-11-08T06:12:00Z", source: "direct" },
  { role: "student", levels: [], subjects: [], boards: [], session: "", status: "new", partial: true, note: "", created: "2026-11-08T05:55:00Z", source: "direct" },
  { role: "parent", levels: ["O-Level"], subjects: ["English Language", "Mathematics"], boards: ["CAIE"], session: "Oct/Nov 2027", phone: "+20 100 000 0004", whatsapp: true, status: "contacted", partial: false, note: "Asked about Arabic. Replied 7 Nov.", created: "2026-11-07T19:03:00Z", source: "waitlist_share" },
  { role: "centre", levels: ["IGCSE", "AS", "A-Level"], subjects: ["Biology", "Chemistry", "Economics", "Physics"], boards: ["CAIE"], session: "", centre: "Example Learning Centre", phone: "+20 100 000 0005", status: "invited", partial: false, note: "Demo booked with Dana (fake).", created: "2026-11-07T11:30:00Z", source: "direct" },
  { role: "student", levels: ["A-Level"], subjects: ["Computer Science", "Mathematics"], boards: ["CAIE"], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-11-07T09:18:00Z", source: "direct" },
  { role: "student", levels: ["IGCSE"], subjects: ["Accounting", "Business", "Economics"], boards: ["CAIE", "Edexcel"], session: "Oct/Nov 2027", status: "declined", partial: false, note: "Asked to be removed.", created: "2026-11-06T20:44:00Z", source: "direct" },
  { role: "teacher", levels: ["AS", "A-Level"], subjects: ["Chemistry"], boards: ["Oxford AQA"], session: "", phone: "+20 100 000 0008", whatsapp: false, status: "contacted", partial: false, note: "", created: "2026-11-06T14:02:00Z", source: "direct" },
  { role: "student", levels: [], subjects: [], boards: [], session: "", status: "new", partial: true, note: "", created: "2026-11-06T10:27:00Z", source: "waitlist_share" },
  { role: "parent", levels: ["IGCSE"], subjects: ["Biology", "Physics"], boards: [], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-11-05T18:50:00Z", source: "direct" },
  { role: "centre", levels: ["IGCSE", "O-Level"], subjects: ["Additional Mathematics", "Mathematics", "Physics"], boards: ["CAIE", "Edexcel"], session: "", centre: "Sample Tutoring Academy", status: "new", partial: false, note: "", created: "2026-11-05T12:15:00Z", source: "direct" },
  { role: "student", levels: ["O-Level"], subjects: ["Islamiyat", "Mathematics"], other: "", boards: ["CAIE"], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-11-04T21:09:00Z", source: "direct" },
  { role: "teacher", levels: ["IGCSE"], subjects: ["Biology", "Other"], other: "Robotics", boards: ["CAIE"], session: "May/June 2027", status: "invited", partial: false, note: "Invited 5 Nov.", created: "2026-11-04T08:33:00Z", source: "direct" },
  { role: "student", levels: ["AS"], subjects: ["Psychology", "Sociology"], boards: ["CAIE"], session: "Oct/Nov 2027", status: "new", partial: false, note: "", created: "2026-11-03T16:41:00Z", source: "waitlist_share" },
  { role: "parent", levels: ["A-Level"], subjects: ["Mathematics", "Physics"], boards: ["CAIE"], session: "May/June 2027", phone: "+20 100 000 0015", whatsapp: true, status: "contacted", partial: false, note: "", created: "2026-11-03T09:05:00Z", source: "direct" },
  { role: "student", levels: ["IGCSE"], subjects: ["French", "Geography", "History"], boards: ["Oxford AQA"], session: "", status: "new", partial: false, note: "", created: "2026-11-02T19:58:00Z", source: "direct" },
  { role: "student", levels: [], subjects: [], boards: [], session: "", status: "new", partial: true, note: "", created: "2026-11-02T13:20:00Z", source: "direct" },
  { role: "teacher", levels: ["IGCSE", "O-Level"], subjects: ["English Language", "English Literature"], boards: ["CAIE"], session: "Oct/Nov 2027", status: "new", partial: false, note: "", created: "2026-11-01T10:11:00Z", source: "direct" },
  { role: "student", levels: ["A-Level"], subjects: ["Biology", "Chemistry"], boards: ["CAIE"], session: "May/June 2027", status: "invited", partial: false, note: "", created: "2026-10-31T17:36:00Z", source: "direct" },
  { role: "centre", levels: ["A-Level"], subjects: ["Economics", "Business"], boards: ["CAIE"], session: "", centre: "Demo Study Hub", status: "contacted", partial: false, note: "", created: "2026-10-30T08:00:00Z", source: "direct" },
  { role: "student", levels: ["IGCSE"], subjects: ["Arabic", "Mathematics"], boards: ["CAIE"], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-10-29T15:47:00Z", source: "waitlist_share" },
  { role: "parent", levels: ["IGCSE"], subjects: ["Chemistry"], boards: [], session: "Oct/Nov 2027", status: "declined", partial: false, note: "", created: "2026-10-28T12:29:00Z", source: "direct" },
  { role: "student", levels: ["O-Level"], subjects: ["Computer Science"], boards: ["CAIE"], session: "May/June 2027", status: "new", partial: false, note: "", created: "2026-10-27T20:14:00Z", source: "direct" },
  { role: "teacher", levels: ["A-Level"], subjects: ["Physics", "Mathematics"], boards: ["CAIE", "Edexcel"], session: "", status: "new", partial: false, note: "", created: "2026-10-26T09:52:00Z", source: "direct" },
]


const LEVEL: Record<string, WaitlistLevel | undefined> = { IGCSE: undefined, "O-Level": "o_level", AS: "as_level", "A-Level": "a_level" }
const BOARD: Record<string, WaitlistBoard> = { CAIE: "caie", Edexcel: "edexcel", "Oxford AQA": "oxford_aqa", Other: "other" }
const SUBJECT: Record<string, string> = { "Art & Design": "art_and_design", "English Language": "english", Islamiyat: "islamic_studies" }
const slug = (label: string) => SUBJECT[label] ?? label.toLowerCase().replace(/ /g, "_")
const SESSION: Record<string, string> = { "May/June 2027": "2027-mj", "Oct/Nov 2027": "2027-on" }

export const APPLICANTS: WaitlistApplicant[] = rows.map((r, i) => ({
  id: String(i + 1),
  email: `${r.role}${String(i + 1).padStart(2, "0")}@example.com`,
  name: NAMES[i] ?? null,
  role: (r.role === "centre" ? "centre_admin" : r.role) as WaitlistRole,
  centreName: r.centre ?? null,
  levels: r.levels.map((l) => LEVEL[l]).filter((l): l is WaitlistLevel => !!l),
  subjects: r.subjects.filter((x) => x !== "Other").map(slug),
  otherSubjects: r.other ? [r.other] : [],
  examBoards: r.boards.map((b) => BOARD[b]),
  examSession: SESSION[r.session] ?? null,
  phone: r.phone ? r.phone.replace(/ /g, "") : null,
  phoneHasWhatsapp: !!r.whatsapp,
  consentText: CONSENT,
  consentVersion: "2026-11-v1",
  emailConfirmed: i === 4 || i === 8,
  consentAt: r.created,
  status: r.status,
  adminNote: r.note || null,
  utmSource: r.source === "direct" ? null : r.source,
  utmMedium: r.source === "direct" ? null : "share", utmCampaign: r.source === "direct" ? null : "launch", utmContent: null, utmTerm: null,
  completedAt: r.partial ? null : r.created,
  partial: r.partial,
  createdAt: r.created,
  updatedAt: r.created,
}))
