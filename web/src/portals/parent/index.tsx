/* Hallmark · pre-emit critique: P4 H4 E4 S4 R4 V4 */
import type { RouteObject } from "react-router-dom"
import { lazy } from "react"
import { PortalNotFound } from "@/portals/misc/NotFound"
import { ParentShell } from "./shell"

// P6.1b: screens are `React.lazy`, not static imports — see the same note in
// `portals/student/index.tsx`. Only four screens here, but the parent portal
// still shipped every one of them (plus the other two portals') on first
// paint before this; the spec's own "two taps to the answer" goal is better
// served by that first paint being as small as possible.
const Children = lazy(() => import("./screens/Children").then((m) => ({ default: m.Children })))
const ChildOverview = lazy(() =>
  import("./screens/ChildOverview").then((m) => ({ default: m.ChildOverview })),
)
const SubjectDetail = lazy(() =>
  import("./screens/SubjectDetail").then((m) => ({ default: m.SubjectDetail })),
)
const Weaknesses = lazy(() => import("./screens/Weaknesses").then((m) => ({ default: m.Weaknesses })))
const ParentNotifications = lazy(() =>
  import("./screens/Notifications").then((m) => ({ default: m.ParentNotifications })),
)
// P-05 to P-08 (tutor marketplace, T27).
const ChildTutoring = lazy(() =>
  import("./screens/tutoring/ChildTutoring").then((m) => ({ default: m.ChildTutoring })),
)
const ParentSessionDetail = lazy(() =>
  import("./screens/tutoring/ParentSessionDetail").then((m) => ({ default: m.ParentSessionDetail })),
)
const ParentChildPlans = lazy(() =>
  import("@/portals/billing/PlansScreen").then((m) => ({ default: m.ParentChildPlans })),
)
const ParentChildBilling = lazy(() =>
  import("@/portals/billing/ParentBilling").then((m) => ({ default: m.ParentChildBilling })),
)
const ParentReceipts = lazy(() =>
  import("@/portals/billing/Receipts").then((m) => ({ default: m.ParentReceipts })),
)
const ChildTutorAccess = lazy(() =>
  import("./screens/tutoring/ChildTutorAccess").then((m) => ({ default: m.ChildTutorAccess })),
)
const ParentFindTutor = lazy(() =>
  import("./screens/tutoring/ParentFindTutor").then((m) => ({ default: m.ParentFindTutor })),
)
const ParentTutorProfile = lazy(() =>
  import("./screens/tutoring/ParentFindTutor").then((m) => ({ default: m.ParentTutorProfile })),
)
const ParentBookSession = lazy(() =>
  import("./screens/tutoring/ParentFindTutor").then((m) => ({ default: m.ParentBookSession })),
)

export const parentRoute: RouteObject = {
  path: "parent",
  element: <ParentShell />,
  children: [
    // P6.5 · `handle.title` on every child. See `lib/meta/documentMeta.ts`.
    // "Your children" rather than a child's name: the route table has an id and
    // no name, and a parent with two children reads the same title on both
    // detail screens, which is the honest limit of what a static title knows.
    {
      index: true,
      element: <Children />,
      handle: { title: "Your children", skeleton: "card-grid" },
    },
    {
      path: "children/:childId",
      element: <ChildOverview />,
      handle: { title: "Progress", skeleton: "page-header" },
    },
    {
      path: "children/:childId/subjects/:code",
      element: <SubjectDetail />,
      handle: { title: "Subject progress", skeleton: "page-header" },
    },
    {
      path: "children/:childId/weaknesses",
      element: <Weaknesses />,
      handle: { title: "Topics to work on", skeleton: "page-header" },
    },
    // F1: the Topics tab. Shows the existing Weaknesses screen until L11 replaces it; /weaknesses stays an alias.
    {
      path: "children/:childId/topics",
      element: <Weaknesses />,
      handle: { title: "Topics to work on", skeleton: "page-header" },
    },
    // P-05 to P-08 (tutor marketplace, T27).
    {
      path: "children/:childId/tutoring",
      element: <ChildTutoring />,
      handle: { title: "Tutoring", skeleton: "list" },
    },
    {
      path: "children/:childId/sessions/:bookingId",
      element: <ParentSessionDetail />,
      handle: { title: "Session details", skeleton: "page-header" },
    },
    {
      path: "children/:childId/tutor-access",
      element: <ChildTutorAccess />,
      handle: { title: "Who they share with", skeleton: "list" },
    },
    {
      path: "children/:childId/billing",
      element: <ParentChildBilling />,
      handle: { title: "Plan and billing", skeleton: "page-header" },
    },
    {
      path: "children/:childId/billing/plans",
      element: <ParentChildPlans />,
      handle: { title: "Plans and credits", skeleton: "page-header" },
    },
    // The payer's own list across every child (receipts belong to the payer). There is no
    // child usage-history route: `/usage/history` serves the caller only (M6).
    {
      path: "billing/receipts",
      element: <ParentReceipts />,
      handle: { title: "Receipts", skeleton: "list" },
    },
    { path: "tutors", element: <ParentFindTutor />, handle: { title: "Tutors", skeleton: "list" } },
    {
      path: "tutors/:tutorId",
      element: <ParentTutorProfile />,
      handle: { title: "Tutor profile", skeleton: "page-header" },
    },
    {
      path: "tutors/:tutorId/book",
      element: <ParentBookSession />,
      handle: { title: "Book a session", skeleton: "page-header" },
    },
    {
      path: "notifications",
      element: <ParentNotifications />,
      handle: { title: "Notifications", skeleton: "list" },
    },
    // P4.10. Last, so it only matches what nothing above did — an unmatched
    // path in this portal used to fall to the top-level `*` and cost the
    // reader the header and the child switcher. See `portals/misc/NotFound.tsx`.
    {
      path: "*",
      element: <PortalNotFound />,
      handle: { title: "Page not found", skeleton: "page-header" },
    },
  ],
}
