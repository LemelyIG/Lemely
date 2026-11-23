/* Hallmark · pre-emit critique: P3 H3 E4 S4 R4 V3 */
import "./subject.css"

/**
 * A refetch failed over a subject that is already on screen (react-query v5 reports "error" and still
 * holds the last good payload). The body stays; this quiet strip sits above it. It is a status, not an
 * alert: nothing the student was reading went away. A failed first load is SubjectError instead.
 */
export function SubjectRefreshNotice({ name, onRetry, pending }: { name: string; onRetry: () => void; pending: boolean }) {
  return (
    <div className="sj-notice" role="status">
      <p>Couldn’t refresh {name}. Showing what loaded before.</p>
      <button type="button" className="sj-notice-go" disabled={pending} onClick={onRetry}>
        Try again
      </button>
    </div>
  )
}
