/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { subjectDotColor } from "./subjects"
import "./redesign.css"

/** A subject's colour dot (mock .sdot). Decorative: the subject name always follows it. */
export function SubjectDot({ subject, size = 8 }: { subject: string; size?: number }) {
  return <i className="rd-dot" aria-hidden="true" style={{ width: size, height: size, background: subjectDotColor(subject) }} />
}
