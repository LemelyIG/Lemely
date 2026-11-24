/* Past papers screen and sheet (L4) view model. Pure; no `.tsx` imports. */
import type { PastPaper } from "@/lib/practiceHubTypes"
import { plural, tryOthers } from "../practiceCopy"

export type PaperOption = "timed" | "print"

export interface PaperRowView {
  paperId: string
  title: string
  sub: string
  score: string | null
  done: boolean
}

export interface PaperGroupView {
  paperNumber: number
  heading: string
  rows: PaperRowView[]
}

export interface PaperSheetView {
  title: string
  sub: string
  options: { key: PaperOption; title: string; body: string }[]
  defaultOption: PaperOption
  hint: string
  printable: boolean
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} min`
  if (m === 0) return `${h} h`
  return `${h} h ${String(m).padStart(2, "0")}`
}

export function paperRow(p: PastPaper): PaperRowView {
  const score = p.awardedMarks !== null && p.maximumMarks !== null ? `${p.awardedMarks}/${p.maximumMarks}` : null
  return {
    paperId: p.paperId,
    title: `${p.code} · ${p.sessionLabel}`,
    sub: p.durationMinutes ? `Paper ${p.paperNumber} · ${formatDuration(p.durationMinutes)}` : `Paper ${p.paperNumber}`,
    score,
    done: score !== null,
  }
}

export function paperGroups(papers: readonly PastPaper[]): PaperGroupView[] {
  const byNumber = new Map<number, PaperRowView[]>()
  for (const p of papers) {
    const rows = byNumber.get(p.paperNumber) ?? []
    rows.push(paperRow(p))
    byNumber.set(p.paperNumber, rows)
  }
  return [...byNumber.entries()]
    .sort(([a], [b]) => b - a)
    .map(([paperNumber, rows]) => ({ paperNumber, heading: `Paper ${paperNumber}`, rows }))
}

export function paperSheetView(p: PastPaper, subjectName: string): PaperSheetView {
  const subParts = [subjectName, `Paper ${p.paperNumber}`]
  if (p.totalMarks) subParts.push(`${p.totalMarks} marks`)
  const options: PaperSheetView["options"] = []
  if (p.durationMinutes) {
    options.push({
      key: "timed",
      title: "Do it timed",
      body: `${formatDuration(p.durationMinutes)} on paper, then type your answers in`,
    })
  }
  options.push({ key: "print", title: "Just print it", body: "No timer. Type your answers in when you're done." })
  return {
    title: `${p.code} · ${p.sessionLabel}`,
    sub: subParts.join(" · "),
    options,
    defaultOption: options[0].key,
    hint: `Prints ${plural(p.questionCount, "question")}. Lemely marks the answers you type in.`,
    printable: p.questionCount > 0,
  }
}

export function emptyPapersCopy(
  subjectName: string,
  otherSubjectNames: readonly string[],
): { heading: string; body: string } {
  return { heading: `No ${subjectName} papers to print yet`, body: tryOthers(otherSubjectNames) }
}
