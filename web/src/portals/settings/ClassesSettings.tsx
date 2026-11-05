/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import { Link, useLocation, useNavigate } from "react-router-dom"
import { ChalkboardTeacher } from "@phosphor-icons/react"
import { buttonVariants } from "@/components/ui/button"
import { ListSkeleton } from "@/components/ui/loading-shapes"
import { QueryState } from "@/components/ui/query-state"
import { EmptyState } from "@/components/ui/state-views"
import { useTeacherClasses } from "@/lib/hooks/useTeacherApi"
import { settingsLoadFailureMessage } from "@/lib/settingsOutcome"
import { cn } from "@/lib/utils"
import { SettingsCard, SettingsRow, SettingsSection } from "./SettingsRows"

/*
 * "Classes and grading", the teacher dialog's links to settings that live
 * with each class.
 *
 * The backend keeps no account-wide grading or class defaults for a teacher
 * (no default subject, review threshold or auto-release). What a teacher can
 * change is per class: its name and subject (`PATCH /classes/{id}`, edited on
 * the Classes screen), its join code (minted on the class page) and its
 * roster. Rather than duplicating those editors in a dialog, this tab lists
 * the teacher's classes and links to where each one is managed, plus the
 * grading alerts that do live in Settings.
 */

const linkButton = cn(buttonVariants({ variant: "secondary" }))

export function ClassesSettingsSection() {
  const classes = useTeacherClasses()
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <>
      <SettingsSection
        title="Your classes"
        description="Open a class for its roster and join code. Rename a class or change its subject from the Classes page."
      >
        <QueryState
          query={classes}
          skeleton={<ListSkeleton rows={3} />}
          error={{ heading: "We couldn't load your classes", body: settingsLoadFailureMessage }}
          isEmpty={(data) => data.classes.length === 0}
          empty={
            <EmptyState
              icon={<ChalkboardTeacher aria-hidden="true" />}
              heading="No classes yet"
              body="Create a class to get a join code for your students."
              action={{ label: "Create a class", onClick: () => navigate("/teacher/first-class") }}
            />
          }
        >
          {(data) => (
            <SettingsCard>
              <ul className="flex flex-col divide-y divide-outline-variant">
                {data.classes.map((cls) => (
                  <li key={cls.id}>
                    <SettingsRow
                      label={cls.label}
                      description={[
                        cls.subjectName ?? "No subject set",
                        `${cls.studentCount} ${cls.studentCount === 1 ? "student" : "students"}`,
                      ].join(" · ")}
                      control={
                        <Link
                          to={`/teacher/classes/${cls.id}`}
                          className={linkButton}
                          aria-label={`Open ${cls.label}`}
                        >
                          Open class
                        </Link>
                      }
                    />
                  </li>
                ))}
              </ul>
              <SettingsRow
                label="Names and subjects"
                description="Rename a class, change its subject or remove it."
                control={
                  <Link to="/teacher/classes" className={linkButton}>
                    Go to Classes
                  </Link>
                }
              />
            </SettingsCard>
          )}
        </QueryState>
      </SettingsSection>

      <SettingsSection
        title="Grading alerts"
        description="At-risk students and withdrawn reviews are notifications, switched on or off with the rest."
      >
        <SettingsCard>
          <SettingsRow
            label="Notification settings"
            description="Choose which grading alerts reach you, and set quiet hours."
            control={
              <Link
                to="/teacher/settings/notifications"
                // Same dialog, so the page underneath stays put.
                state={location.state}
                replace
                className={linkButton}
              >
                Open Notifications
              </Link>
            }
          />
        </SettingsCard>
      </SettingsSection>
    </>
  )
}
