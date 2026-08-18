/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import { Link } from "react-router-dom"
import { Card, CardBody } from "@/components/ui/card"
import { Eyebrow } from "@/components/ui/primitives"
import { Badge } from "@/components/ui/badge"
import { subjectToneForCode } from "@/components/ui/subject-tag"
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table"
import { EmptyState, ErrorState } from "@/components/ui/state-views"
import { ListSkeleton, PageHeaderSkeleton } from "@/components/ui/loading-shapes"
import { adminLoadFailureMessage } from "@/lib/adminOutcome"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"

/**
 * K-04 · Classes, school-wide.
 *
 * Reads `GET /api/teacher/classes`, which is not the misnomer it looks like:
 * `ClassService.list_classes` branches on the caller's role, and for a
 * `school_admin` it returns every class whose `school_id` is a school they hold
 * a membership for. This screen is therefore genuinely school-wide, and needs
 * no endpoint of its own.
 *
 * ── What this screen deliberately cannot do, and says so ───────────────────
 *
 * K-04 lists four capabilities: see, **create**, **reassign**, **archive**.
 * Only the first is honest here, and the panel at the bottom of the screen
 * states why rather than shipping three buttons that would 403 or lie:
 *
 * * **Create** is `POST /api/classes`, gated to `teacher` alone
 *   (`tests/test_authz_matrix_complete.py`). A school admin pressing a Create
 *   button would get a 403 from a screen that had invited them to press it.
 * * **Archive** does not exist at any level. `classes` has no `archived`
 *   column and no route sets one; the only thing resembling it is
 *   `DELETE /api/classes/{id}`, which is destruction rather than archival and
 *   is also teacher-only. Wiring "Archive" to a delete would be the worst
 *   option on this screen by a distance.
 * * **Reassign** exists, but as a *staffing* act rather than a per-class one:
 *   removing a teacher on K-03 moves every class they own to a named
 *   successor. So the screen points there instead of pretending to a control
 *   it does not have.
 *
 * This is the "either build it or say plainly the screen cannot be honest yet"
 * half of D1.6, and it is deliberately not padded out with a disabled button.
 */
export function Classes() {
  const { data, isPending, isError, error } = useTeacherClasses()

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <Eyebrow>School admin</Eyebrow>
        <h1 className="text-display-lg text-ink">Classes</h1>
        <p className="max-w-prose text-body-md text-ink-muted">
          Every class in your school, whoever teaches it.
        </p>
      </header>

      {isPending ? (
        <>
          <PageHeaderSkeleton />
          <ListSkeleton rows={5} />
        </>
      ) : isError ? (
        <ErrorState
          heading="We couldn't load your classes"
          body={adminLoadFailureMessage(error)}
          action={{ label: "Try again", onClick: () => window.location.reload() }}
        />
      ) : data.classes.length === 0 ? (
        <EmptyState
          marginalia="no classes on the register"
          heading="No classes yet"
          body="Your teachers create their own classes. Once one does, it appears here with its roll and how the class is doing."
        />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>Class</TH>
              <TH>Subject</TH>
              <TH numeric>Students</TH>
              {/* Named exactly what it is. It is the mean of each student's
                  latest paper percentage, and it is emphatically not a class
                  predicted grade: averaging letter grades invents precision
                  the data does not support (D3.12). */}
              <TH numeric>Average mark</TH>
              <TH numeric>At risk</TH>
            </tr>
          </THead>
          <TBody>
            {data.classes.map((schoolClass) => (
              <TR key={schoolClass.id}>
                <TD>
                  {/* A real link, not a row click handler: a class detail page
                      is a destination, and a destination is an anchor. */}
                  {/* `data-wraps-content-title` opts this out of §6.1's
                      two-line-clickable-text rule, deliberately and narrowly:
                      the label is a class name the school typed, so the only
                      alternatives to wrapping are truncating it or letting it
                      overflow, and both cost the reader information the product
                      does not own. See scripts/adapt_audit.mjs. */}
                  <Link
                    to={`/teacher/classes/${schoolClass.id}`}
                    data-wraps-content-title
                    className="text-body-sm text-accent-ink hover:underline"
                  >
                    {schoolClass.label}
                  </Link>
                </TD>
                <TD>
                  {schoolClass.subjectCode ? (
                    // A bare syllabus code, so the tone comes from
                    // `subjectToneForCode` rather than `SubjectTag`'s
                    // name-based lookup, which would fall back to "other" for
                    // every class in the school.
                    <div className="flex items-center gap-2">
                      <Badge tone={subjectToneForCode(schoolClass.subjectCode)}>
                        {schoolClass.subjectName ?? schoolClass.subjectCode}
                      </Badge>
                      {/* Omitted when the name has resolved to the code
                          itself — a class's `subjectCode` is free text a
                          teacher typed, so most classes hit the det
                          registry's default profile (name === code, see
                          `subjectIdentifier`'s docstring) and this element
                          would otherwise print the same code twice. */}
                      {(schoolClass.subjectName ?? schoolClass.subjectCode) !== schoolClass.subjectCode ? (
                        <span className="text-data-sm text-ink-faint">{schoolClass.subjectCode}</span>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-body-sm text-ink-faint">Not set</span>
                  )}
                </TD>
                <TD numeric>{schoolClass.studentCount}</TD>
                <TD numeric>
                  {schoolClass.average === null ? (
                    // Never 0%. An empty class and a class that scored nothing
                    // are different facts, and one of them is not a mark.
                    <span className="text-body-sm text-ink-faint">No papers yet</span>
                  ) : (
                    `${Math.round(schoolClass.average)}%`
                  )}
                </TD>
                <TD numeric>
                  {schoolClass.atRiskCount === null ? (
                    <span className="text-body-sm text-ink-faint">Unknown</span>
                  ) : (
                    schoolClass.atRiskCount
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}

      <Card>
        <CardBody className="flex flex-col gap-2">
          <Eyebrow>Making changes</Eyebrow>
          <p className="max-w-prose text-body-sm text-ink-muted">
            Classes are created and renamed by the teacher who runs them, so those controls live
            in the teaching tools rather than here. To move classes between teachers, remove the
            teacher on the{" "}
            <Link to="/school/teachers" className="text-accent-ink hover:underline">
              Teachers
            </Link>{" "}
            screen and name who takes them over. There is no way to archive a class yet.
          </p>
        </CardBody>
      </Card>
    </div>
  )
}
