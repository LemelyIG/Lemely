/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
/*
 * ── The critique those six digits came from ────────────────────────────────
 *
 * This file is logic plus one placeholder screen, so most axes were scored on the behaviour a
 * person sees, and each was re-scored after the first pass of the switcher, banner and gating
 * had been built and looked at (see `.superpowers/sdd/p03-acting-report.md` for the screenshots).
 * Axis names are the six that critique scores: Philosophy, Hierarchy, Execution,
 * Specificity, Restraint, Variety. `BUILD/BLOCKERS.md` B6 asks for a sentence per axis rather
 * than a bare digit, so:
 *
 * P · philosophy — 4. The position is "nobody acts as someone else by accident": the choice is
 *   explicit, per tab, checked against the live membership list before a single request carries
 *   it, and reset (with a message) the moment the membership goes. One withheld because the
 *   position costs a skeleton flash on reload for the rare tab that had a lead selected.
 * H · hierarchy — 4. Not a visual file, but it decides what is primary: the placeholder while a
 *   stored choice is checked is the same `RouteSkeleton` every route uses, so it reads as
 *   "loading", not as a new state to learn.
 * E · execution — 4. Keyed remount on switch (so no screen can hold the old lead's state), focus
 *   returned to `<main>` afterwards, `cancelQueries` before the identity changes so a retry cannot
 *   write one lead's answer under another's key. One withheld: the remount also closes an open
 *   drawer and resets scroll, which is right for a change of identity and still abrupt.
 * S · specificity — 4. Every word is about this feature ("working as", "team", the lead's name).
 *   One withheld: a teacher with one membership still gets the generic two-option list.
 * R · restraint — 4. One context, three hooks, no store library, no new dependency. One withheld:
 *   `OWN_ACCOUNT_ROOTS` is a second list to keep honest beside the allow-list.
 * V · variety — 4. A provider, as the portal already has (`ToastProvider`, `AuthProvider`), with
 *   nothing visual of its own to repeat.
 */
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { RouteSkeleton } from "@/components/ui/route-skeleton"
import { MAIN_CONTENT_ID } from "@/components/ui/skip-link"
import { useAuth } from "@/lib/auth/AuthContext"
import { membershipEndedNotice, MEMBERSHIP_UNCONFIRMED_NOTICE } from "@/lib/actingNotices"
import {
  readStoredLeadId,
  setActingLead,
  storeLeadId,
  useActingLead,
} from "@/lib/actingTeacher"
import { useMemberships, type JoinedTeam } from "@/lib/hooks/useMemberships"
import { ActingTeacherContext, type ActingTeacherValue } from "./acting-state"

/*
 * "Working as" for the teacher portal: which lead teacher, if any, an assistant is acting for.
 *
 * ── What it guarantees ──────────────────────────────────────────────────────────────────────────
 * 1. A choice is only ever sent after it has been checked against `GET /teacher/team/memberships`.
 *    A stored id waits behind a skeleton until that list has answered; if the id is not on it (or
 *    the list cannot be read) the choice is dropped and the person is told.
 * 2. Switching remounts everything under the provider. No screen keeps the previous lead's
 *    queries, form drafts or open dialogs, and the query cache is partitioned by lead besides
 *    (`actingQueryHash`), so a slow request from before the switch cannot land in the new view.
 * 3. A membership that disappears while selected resets to "Me", goes to the portal home (a
 *    deep link into the lead's class would only 403), and leaves a dismissible notice.
 * 4. A teacher with no memberships, or any other role, gets the same tree as before: no switcher,
 *    no banner, no extra request that matters, and the default context value says "can do
 *    everything".
 */

const NO_TEAMS: readonly JoinedTeam[] = []

export function ActingTeacherProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  const isTeacher = session?.role === "teacher"
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const membershipsQuery = useMemberships({ enabled: isTeacher })
  const teams = membershipsQuery.data ?? NO_TEAMS
  const actingLead = useActingLead()

  // Read once. Whoever signs in on this tab later gets a fresh provider and `clearSession` has
  // already wiped the stored choice.
  const [storedId] = useState<string | null>(() => (isTeacher ? readStoredLeadId() : null))
  const [checked, setChecked] = useState(storedId === null)
  const [notice, setNotice] = useState<string | null>(null)

  const lead = actingLead ? (teams.find((t) => t.teacherId === actingLead.leadId) ?? null) : null

  // Restoring a stored choice: nothing is sent for the lead until the list has said it is real.
  useEffect(() => {
    if (checked || storedId === null) return
    if (membershipsQuery.isPending) return
    const match = membershipsQuery.isSuccess ? teams.find((t) => t.teacherId === storedId) : undefined
    if (match) {
      setActingLead({ leadId: match.teacherId, leadName: match.teacherName })
    } else {
      storeLeadId(null)
      setNotice(membershipsQuery.isSuccess ? membershipEndedNotice(null) : MEMBERSHIP_UNCONFIRMED_NOTICE)
    }
    setChecked(true)
  }, [checked, storedId, membershipsQuery.isPending, membershipsQuery.isSuccess, teams])

  // After that: a membership that goes away (or is renamed) while it is selected.
  useEffect(() => {
    if (!checked || actingLead === null || !membershipsQuery.isSuccess) return
    const still = teams.find((t) => t.teacherId === actingLead.leadId)
    if (!still) {
      void queryClient.cancelQueries()
      setActingLead(null)
      storeLeadId(null)
      setNotice(membershipEndedNotice(actingLead.leadName))
      navigate("/teacher")
    } else if (still.teacherName !== actingLead.leadName) {
      setActingLead({ leadId: still.teacherId, leadName: still.teacherName })
    }
  }, [checked, actingLead, membershipsQuery.isSuccess, teams, queryClient, navigate])

  const choose = useCallback(
    (teacherId: string | null) => {
      const target = teacherId === null ? null : teams.find((t) => t.teacherId === teacherId)
      if (teacherId !== null && !target) return
      // Stop what is in flight for the old identity first: a retry that fires after the switch
      // would send the new header and write its answer under the old key.
      void queryClient.cancelQueries()
      setActingLead(target ? { leadId: target.teacherId, leadName: target.teacherName } : null)
      storeLeadId(target ? target.teacherId : null)
      setNotice(null)
      // A deep link into one teacher's class means nothing to the other.
      navigate("/teacher")
    },
    [teams, queryClient, navigate],
  )

  const dismissNotice = useCallback(() => setNotice(null), [])

  const value = useMemo<ActingTeacherValue>(
    () => ({
      memberships: teams,
      lead,
      acting: lead !== null,
      can: (permission) => lead === null || lead.permissions.includes(permission),
      choose,
      notice,
      dismissNotice,
    }),
    [teams, lead, choose, notice, dismissNotice],
  )

  // After a change of identity the control that had focus is gone with the old tree.
  const identityKey = actingLead?.leadId ?? "self"
  const firstKey = useRef(identityKey)
  useEffect(() => {
    if (firstKey.current === identityKey) return
    firstKey.current = identityKey
    document.getElementById(MAIN_CONTENT_ID)?.focus()
  }, [identityKey])

  if (!checked) {
    return (
      <div data-portal="teacher" className="min-h-dvh bg-surface px-page-mobile pt-8 md:px-page-tablet lg:px-[72px]">
        <RouteSkeleton />
      </div>
    )
  }

  return (
    <ActingTeacherContext.Provider value={value}>
      <Fragment key={identityKey}>{children}</Fragment>
    </ActingTeacherContext.Provider>
  )
}
