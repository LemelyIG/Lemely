import {
  STUDENT_PROFILE,
  studentShellMocks,
  teacherShellMocks,
} from "./mocks.mjs";
import { DETAIL_PATH } from "./scenes-native.mjs";

export const NATIVE_HOME = {
  path: "/student",
  profile: STUDENT_PROFILE,
  mocks: studentShellMocks("populated"),
};
export const NATIVE_TEACHER_HOME = {
  surface: "teacher-overview",
  state: "populated",
  mocks: teacherShellMocks,
};
/** A teacher detail page (trail deeper than a section root); any mocked 404 body still renders the shell bar. */
export const NATIVE_TEACHER_DETAIL = {
  ...NATIVE_TEACHER_HOME,
  path: "/teacher/announcements",
};

const TUTOR_DIRECTORY = {
  items: [
    {
      tutorId: "tutor-1",
      publicName: "Dina Farouk",
      headline: "IGCSE Physics and Maths, past-paper drills every week",
      subjects: [{ code: "0625", name: "Physics" }],
      modes: ["virtual", "in_person"],
      area: { code: "cairo", name: "Cairo" },
      rating: { state: "rated", average: 4.8, count: 12 },
    },
  ],
  nextCursor: null,
  facets: { subjects: [{ code: "0625", name: "Physics" }], areas: [{ code: "cairo", name: "Cairo" }] },
}

export const NATIVE_FIND_TUTOR = {
  path: "/student/tutors",
  profile: STUDENT_PROFILE,
  mocks: async (page) => {
    await studentShellMocks("populated")(page)
    await page.route(/\/api\/tutors(\?|$)/, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TUTOR_DIRECTORY) }),
    )
  },
}

const SUBJECT_DETAIL = {
  header: {
    name: "Add Maths",
    code: "0606",
    qualificationLevel: "IGCSE",
    intro: "Where you stand in Additional Mathematics.",
    forecast: "B",
    weightedMean: "62",
    weightedMeanDelta: "+4 since first paper",
  },
  papersBreakdown: [],
  topicMap: [],
  paperHistory: [],
}

export const NATIVE_SUBJECT = {
  path: "/student/subject/0606",
  profile: STUDENT_PROFILE,
  mocks: async (page) => {
    await studentShellMocks("populated")(page)
    await page.route(/\/api\/student\/subject\/0606(\?|$)/, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SUBJECT_DETAIL) }),
    )
  },
}

/** Each check: { id, platform, width (default 390), theme, app, run(page) }. */
const jsonRoute = (route, body) =>
  route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })

const CLASS_DETAIL = {
  id: "class-1",
  label: "Year 11 Physics",
  stats: [],
  mastery: [],
  distribution: [],
  students: [],
  subjectCode: "0625",
  subjectName: "Physics",
  schoolId: null,
  joinCode: null,
  atRiskCount: 0,
  lastActivityAt: null,
  topWeakness: null,
}

const classPaper = (n, studentName, unshared) => ({
  attemptId: `attempt-${n}`,
  studentId: `student-${n}`,
  studentName,
  subjectCode: "0625",
  paperNumber: 2,
  paperVariant: 1,
  sessionMonth: "May/June",
  sessionYear: 2026,
  recordedAt: "2026-11-12T08:00:00Z",
  unshared,
})

const AT_RISK_LIST = (omarAcknowledged) => {
  const flag = (reason, acknowledged = null) => ({ reason, summary: reason, evidence: {}, acknowledged })
  return {
    students: [
      { studentId: "s-1", displayName: "Amina Said", classId: "class-1", className: "Year 11 Physics", grade: "C", flags: [flag("declining_trend"), flag("below_target")] },
      {
        studentId: "s-2",
        displayName: "Omar Nabil",
        classId: "class-1",
        className: "Year 11 Physics",
        grade: "D",
        flags: [flag("below_target", omarAcknowledged ? { acknowledgedAt: "2026-11-13T09:00:00Z", note: "Spoke to him" } : null)],
      },
      { studentId: "s-3", displayName: "Layla Hassan", classId: "class-1", className: "Year 11 Physics", grade: "E", flags: [flag("declining_trend"), flag("below_target"), flag("inactive")] },
    ],
  }
}

const CLASS_ROWS = [
  { id: "class-1", label: "Year 11 Physics", studentCount: 24, average: 64.2, subjectCode: "0625", subjectName: "Physics", schoolId: null, joinCode: null, atRiskCount: 2, lastActivityAt: null, topWeakness: null },
  { id: "class-2", label: "Year 10 Maths", studentCount: 1, average: null, subjectCode: null, subjectName: null, schoolId: null, joinCode: null, atRiskCount: 0, lastActivityAt: null, topWeakness: null },
  { id: "class-3", label: "AS Chemistry", studentCount: 18, average: 71, subjectCode: "9701", subjectName: "Chemistry", schoolId: null, joinCode: null, atRiskCount: null, lastActivityAt: null, topWeakness: null },
]

const QUIZ_ROWS = [
  { id: "quiz-1", subjectCode: "0625", title: "Forces recap", status: "published", targetGrade: "B", includedTopics: [], poolSource: null, requestedCount: 10, timeLimitMinutes: null, builderStep: 6, questionCount: 10 },
  { id: "quiz-2", subjectCode: "0606", title: "Quadratics warm-up", status: "draft", targetGrade: null, includedTopics: [], poolSource: null, requestedCount: null, timeLimitMinutes: null, builderStep: 3, questionCount: 4 },
]

const ANALYTICS = {
  topicWeaknesses: [],
  heatmap: [],
  gradeDistribution: [],
  trend: [],
  paperComparison: [
    { paperId: "0625-2-2", subjectCode: "0625", paperNumber: 2, paperVariant: 2, meanPercentage: 64.5, attemptCount: 6, studentCount: 4 },
    { paperId: "0625-4-1", subjectCode: "0625", paperNumber: 4, paperVariant: 1, meanPercentage: 58, attemptCount: 4, studentCount: 3 },
  ],
  engagement: { submissionsLast7Days: 5, submissionsLast30Days: 14, activeStudentsLast7Days: 3, activeStudentsLast30Days: 4, neverActiveCount: 0, medianDaysSinceLastSubmission: 3 },
}

const STUDENT = {
  studentId: "s-yusuf",
  displayName: "Yusuf Adel",
  subjects: [{ subjectCode: "0625", predictedGrade: "E", latestPercentage: 44, paperCount: 2 }],
  attempts: [
    { paperId: "0625-4-1", subjectCode: "0625", paperNumber: 4, paperVariant: 1, awardedMarks: 35, maximumMarks: 80, percentage: 43.75, grade: "E", recordedAt: "2026-07-28T08:10:00+00:00" },
    { paperId: "0625-2-2", subjectCode: "0625", paperNumber: 2, paperVariant: 2, awardedMarks: 21, maximumMarks: 40, percentage: 52.5, grade: "D", recordedAt: "2026-06-15T09:00:00+00:00" },
  ],
  weaknesses: [],
  trend: [],
  isAtRisk: false,
  atRiskFlags: [],
  engagement: { totalPapers: 2, lastActiveAt: "2026-07-28T08:10:00+00:00", daysSinceLastSubmission: 17 },
}

/** The table's own scroll region (labelled and focusable on the Table), the only one in table view. */
const tableRegion = (page) => page.locator(".lm-native-main").getByRole("region").filter({ has: page.locator("table") });

/** A teacher table screen on a phone: list rows first, no table in the DOM, then
 * View table swaps in the scrollable region, and the choice survives a reload. */
async function expectListThenTable(page, { label, storageKey, rowSelector, rows }) {
  const list = page.locator(rowSelector)
  await list.first().waitFor()
  if ((await list.count()) !== rows) throw new Error(`${label}: expected ${rows} list rows, found ${await list.count()}`)
  if ((await page.locator(".lm-native-main table").count()) !== 0) throw new Error(`${label}: table rendered in list view`)
  await page.getByRole("button", { name: "View table" }).click()
  const region = tableRegion(page)
  await region.waitFor()
  const bodyRows = await region.locator("tbody tr").count()
  if (bodyRows !== rows) throw new Error(`${label}: expected ${rows} table body rows, found ${bodyRows}`)
  await page.reload({ waitUntil: "networkidle" })
  await tableRegion(page).waitFor()
  const stored = await page.evaluate((k) => sessionStorage.getItem(k), storageKey)
  if (stored !== "table") throw new Error(`${label}: table choice not persisted, sessionStorage=${stored}`)
}

export const NATIVE_CHECKS = [
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-platform-resolves`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(
        () => document.documentElement.dataset.platform,
      );
      if (got !== platform) throw new Error(`data-platform=${got}`);
    },
  })),
  {
    id: "native-other-keeps-design-a",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate(
        () => document.documentElement.dataset.platform,
      );
      if (got !== "other")
        throw new Error(`no UA override should resolve to other, got ${got}`);
    },
  },
];
NATIVE_CHECKS.push(
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-large-title-collapses`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const header = page.locator("header[data-title-level]");
      if ((await header.getAttribute("data-title-level")) !== "root")
        throw new Error("/student should be a root");
      const large = page.locator("[data-shell-large-title]");
      if (!(await large.isVisible()))
        throw new Error("large title hidden at the top of a root");
      const box = await large.boundingBox();
      await page.evaluate((y) => window.scrollTo(0, y - 1), box.height);
      await page.waitForTimeout(80);
      if ((await header.getAttribute("data-collapsed")) !== "false")
        throw new Error("collapsed 1px before the threshold");
      await page.evaluate((y) => window.scrollTo(0, y), box.height);
      await page.waitForFunction(
        () =>
          document.querySelector("header[data-title-level]").dataset
            .collapsed === "true",
      );
      const inline = page.locator("header [data-shell-title]");
      const opacity = await inline.evaluate(
        (el) => getComputedStyle(el).opacity,
      );
      if (opacity !== "1")
        throw new Error(`inline title opacity ${opacity} after collapse`);
      const sticky = await header.evaluate(
        (el) => getComputedStyle(el).position,
      );
      if (sticky !== "sticky") throw new Error(`bar position ${sticky}`);
    },
  })),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-detail-has-back`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: DETAIL_PATH },
    async run(page) {
      const header = page.locator("header[data-title-level]");
      if ((await header.getAttribute("data-title-level")) !== "detail")
        throw new Error("practice page should be a detail");
      if (await page.locator("[data-shell-large-title]").isVisible())
        throw new Error("detail shows a large title");
      const backs = await page
        .getByRole("button", { name: /back/i })
        .or(page.getByRole("link", { name: /back/i }))
        .filter({ visible: true })
        .count();
      if (backs !== 1)
        throw new Error(`expected one visible back control, got ${backs}`);
      const label = page.locator("header .lm-native-back-label");
      if ((await label.isVisible()) !== (platform === "ios"))
        throw new Error("the back label shows on iOS only");
      if (platform === "ios") {
        const back = await page.locator("header .lm-native-back").boundingBox();
        const text = await label.boundingBox();
        if (!back || !text) throw new Error("iOS back or its label has no box");
        if (back.width <= 44)
          throw new Error(`iOS back is ${back.width}px wide, not chevron plus label`);
        const contained =
          text.x >= back.x - 0.5 &&
          text.x + text.width <= back.x + back.width + 0.5 &&
          text.y >= back.y - 0.5 &&
          text.y + text.height <= back.y + back.height + 0.5;
        if (!contained)
          throw new Error(
            `iOS back box ${JSON.stringify(back)} does not contain its label ${JSON.stringify(text)}`,
          );
      }
      for (const action of ["settings", "account"]) {
        if (
          await page
            .locator(`header [data-shell-action="${action}"] :is(a, button)`)
            .first()
            .isVisible()
        )
          throw new Error(`detail shows the ${action} action`);
      }
    },
  })),
  {
    id: "native-ios-teacher-root-title-clears-actions",
    platform: "ios",
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const header = page.locator("header[data-title-level]");
      await page.evaluate(() => window.scrollTo(0, 100000));
      await page.waitForFunction(
        () =>
          document.querySelector("header[data-title-level]").dataset
            .collapsed === "true",
      );
      const title = await page.locator("header [data-shell-title]").boundingBox();
      const actions = header.locator(":is(a, button):visible");
      const n = await actions.count();
      if (n !== 3) throw new Error(`teacher root shows ${n} actions, expected 3 (Create left the bar)`);
      for (let i = 0; i < n; i++) {
        const box = await actions.nth(i).boundingBox();
        const overlaps =
          title.x < box.x + box.width &&
          box.x < title.x + title.width &&
          title.y < box.y + box.height &&
          box.y < title.y + title.height;
        if (overlaps)
          throw new Error(
            `collapsed title ${JSON.stringify(title)} intersects action ${i} ${JSON.stringify(box)}`,
          );
      }
    },
  },
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-teacher-detail-one-action`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_DETAIL,
    async run(page) {
      const header = page.locator("header[data-title-level]");
      if ((await header.getAttribute("data-title-level")) !== "detail")
        throw new Error("teacher detail route should be a detail");
      const names = await header
        .locator(":is(a, button):visible")
        .evaluateAll((els) =>
          els.map((e) => e.getAttribute("aria-label") || e.textContent.trim()),
        );
      const actions = names.filter((n) => !/^Back/.test(n));
      if (actions.length !== 1)
        throw new Error(`expected one action beside back, got ${JSON.stringify(names)}`);
      if (!/notif/i.test(actions[0]))
        throw new Error(`the one action should be the bell, got ${actions[0]}`);
    },
  })),
  {
    id: "native-other-has-no-large-title",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if (await page.locator("[data-shell-large-title]").isVisible())
        throw new Error("other platform shows the native large title");
    },
  },
);

/** A real nested page under the active Classes tab (teacher `classes/:classId`).
 * The tab stays active by prefix match; the re-tap logic reads only the pathname. */
export const TAB_DRILL_PATH = "/teacher/classes/c1";

NATIVE_CHECKS.push(
  {
    id: "native-ios-tab-retap-scrolls-to-top",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/classes" },
    async run(page) {
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px";
        window.scrollTo(0, 600);
      });
      const tab = page
        .getByRole("navigation", { name: "Primary" })
        .getByRole("link", { name: "Classes" });
      await tab.click();
      await page.waitForFunction(() => window.scrollY === 0);
      if (new URL(page.url()).pathname !== "/student/classes")
        throw new Error("a tap while scrolled navigated");
    },
  },
  {
    id: "native-ios-tab-retap-pops-to-root",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_TEACHER_HOME, path: TAB_DRILL_PATH },
    async run(page) {
      const tab = page
        .getByRole("navigation", { name: "Primary" })
        .getByRole("link", { name: "Classes" });
      await tab.click();
      await page.waitForURL(/\/teacher\/classes$/);
    },
  },
  {
    id: "native-android-immersive-hides-tabs",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/correct" },
    async run(page) {
      if (await page.getByRole("navigation", { name: "Primary" }).isVisible())
        throw new Error("tab bar shows on an immersive route");
    },
  },
  {
    id: "native-android-tabs-show-off-immersive",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if (!(await page.getByRole("navigation", { name: "Primary" }).isVisible()))
        throw new Error("tab bar hidden on a normal route");
    },
  },
);

NATIVE_CHECKS.push({
  id: "native-ios-sheet-drag-dismiss-and-escape",
  platform: "ios",
  width: 390,
  app: NATIVE_TEACHER_HOME,
  async run(page) {
    const trigger = page.getByRole("button", { name: /^Create/ }).first()
    await trigger.click()
    const dialog = page.getByRole("dialog")
    await dialog.waitFor()
    const grab = dialog.locator(".lm-sheet-grabber")
    const box = await grab.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + 2)
    await page.mouse.down()
    const startY = box.y + 2
    const delta = 58
    await page.mouse.move(box.x + box.width / 2, startY + delta, { steps: 4 })
    // Mid-drag the sheet sits exactly one finger delta below rest, with no transition lagging it.
    const mid = await dialog.evaluate((el) => ({ translate: el.style.translate, dragging: el.hasAttribute("data-dragging"), transition: getComputedStyle(el).transitionProperty }))
    if (mid.translate !== `0px ${delta}px`) throw new Error(`sheet translate ${mid.translate} != finger delta ${delta}px mid-drag`)
    if (!mid.dragging || mid.transition !== "none") throw new Error(`sheet still transitions mid-drag (${JSON.stringify(mid)})`)
    await page.mouse.move(box.x + box.width / 2, box.y + 400, { steps: 8 })
    await page.mouse.up()
    await dialog.waitFor({ state: "detached" })
    if (!(await trigger.evaluate((el) => el === document.activeElement))) throw new Error("focus did not return to the trigger after drag-dismiss")
    await trigger.click()
    await dialog.waitFor()
    await page.keyboard.press("Escape")
    await dialog.waitFor({ state: "detached" })
  },
})

NATIVE_CHECKS.push(
  ...[
    ["ios", "native-tabbar-h-ios"],
    ["android", "native-tabbar-h-android"],
  ].map(([platform, token]) => ({
    id: `native-${platform}-tabbar-height-matches-token`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const got = await page.evaluate((tokenName) => {
        const probe = document.createElement("div");
        probe.style.blockSize = `calc(var(--${tokenName}) + env(safe-area-inset-bottom))`;
        document.body.append(probe);
        const want = probe.getBoundingClientRect().height;
        probe.remove();
        const nav = document.querySelector("nav.lm-native-tabbar");
        const main = document.querySelector(".lm-native-main");
        const pad = parseFloat(getComputedStyle(main).paddingBottom);
        const navBox = nav.getBoundingClientRect();
        const labelBottom = Math.max(
          ...[...nav.querySelectorAll(".lm-native-tab-label")].map((l) => l.getBoundingClientRect().bottom),
        );
        return { want, height: navBox.height, pad, labelFits: labelBottom <= navBox.bottom + 0.5 };
      }, token);
      if (Math.abs(got.height - got.want) > 0.5)
        throw new Error(`tab bar height ${got.height}px != token ${got.want}px`);
      if (!got.labelFits) throw new Error("tab labels spill below the bar");
      if (Math.abs(got.pad - got.want) > 0.5)
        throw new Error(`main padding ${got.pad}px != tab bar ${got.want}px`);
    },
  })),
  ...[
    ["ios", 600],
    ["android", 700],
  ].map(([platform, selected]) => ({
    id: `native-${platform}-tab-label-weights`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const w = await page.evaluate(() => {
        const labelOf = (link) => getComputedStyle(link.querySelector(".lm-native-tab-label")).fontWeight;
        const plain = [...document.querySelectorAll("nav.lm-native-tabbar > *")].filter(
          (l) => !l.querySelector("[data-emphasis]"),
        );
        const sel = plain.find((l) => l.getAttribute("aria-current") === "page");
        const rest = plain.find((l) => l.getAttribute("aria-current") !== "page");
        return { selected: sel && labelOf(sel), unselected: rest && labelOf(rest) };
      });
      if (w.selected !== String(selected))
        throw new Error(`selected tab label weight ${w.selected} != ${selected}`);
      if (w.unselected !== "500") throw new Error(`unselected tab label weight ${w.unselected} != 500`);
    },
  })),
  {
    id: "native-android-active-pill-centred-clear",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const r = await page.evaluate(() => {
        const link = document.querySelector('nav.lm-native-tabbar [aria-current="page"]');
        const icon = link.querySelector(".lm-native-tab-icon");
        const pseudo = getComputedStyle(icon, "::before");
        const ib = icon.getBoundingClientRect();
        const left = ib.left + parseFloat(pseudo.left);
        const width = parseFloat(pseudo.width);
        const lb = link.getBoundingClientRect();
        const circle = document
          .querySelector("nav.lm-native-tabbar [data-emphasis]")
          .getBoundingClientRect();
        return {
          pillCentre: left + width / 2,
          iconCentre: ib.left + ib.width / 2,
          inLink: left >= lb.left - 0.5 && left + width <= lb.right + 0.5,
          hitsCircle: left < circle.right && left + width > circle.left,
        };
      });
      if (Math.abs(r.pillCentre - r.iconCentre) > 0.5)
        throw new Error(`pill centre ${r.pillCentre} != icon centre ${r.iconCentre}`);
      if (!r.inLink) throw new Error("pill spills into a neighbouring tab");
      if (r.hitsCircle) throw new Error("pill overlaps the Correct circle");
    },
  },
);
NATIVE_CHECKS.push({
    id: "native-android-tutor-card-centred",
    platform: "android",
    width: 390,
    app: NATIVE_FIND_TUTOR,
    async run(page) {
      const gaps = await page.evaluate(() => {
        const card = document.querySelector(".lm-native-main ul > li > .lm-native-card")
        if (!card) return null
        const r = card.getBoundingClientRect()
        return { left: r.left, right: window.innerWidth - r.right, width: r.width }
      })
      if (!gaps) throw new Error("no .lm-native-card on Find a tutor (mock not served?)")
      if (Math.abs(gaps.left - gaps.right) > 0.5 || gaps.left < -0.5)
        throw new Error(`tutor card not centred: left ${gaps.left}px, right ${gaps.right}px`)
      if (gaps.left > 0.5) throw new Error(`tutor card not full-bleed: gap ${gaps.left}px`)
    },
  },
);
NATIVE_CHECKS.push({
    id: "native-android-subject-stats-side-by-side",
    platform: "android",
    width: 390,
    app: NATIVE_SUBJECT,
    async run(page) {
      await page.getByText("Forecast grade").waitFor()
      const tiles = await page.evaluate(() => {
        const cards = [...document.querySelectorAll(".lm-native-main .lm-native-card")].filter((c) =>
          /Forecast grade|Weighted mean/.test(c.textContent ?? ""),
        )
        return cards.map((c) => {
          const r = c.getBoundingClientRect()
          return { top: r.top, left: r.left, right: r.right, vw: window.innerWidth }
        })
      })
      if (tiles.length !== 2) throw new Error(`expected 2 stat tiles, found ${tiles.length}`)
      if (Math.abs(tiles[0].top - tiles[1].top) > 0.5)
        throw new Error(`stat tiles stacked: tops ${tiles[0].top}px / ${tiles[1].top}px`)
      for (const t of tiles)
        if (t.left < -0.5 || t.right > t.vw + 0.5) throw new Error(`stat tile overflows viewport: ${t.left}..${t.right} of ${t.vw}`)
    },
  },
  {
    id: "native-android-review-list-and-table",
    platform: "android",
    width: 390,
    app: {
      surface: "teacher-overview",
      state: "populated",
      path: "/teacher/review",
      mocks: async (page) => {
        await teacherShellMocks(page)
        const item = (n) => ({
          itemId: `item-${n}`,
          source: "attempt",
          attemptId: `attempt-${n}`,
          paperId: null,
          questionResultId: `qr-${n}`,
          studentId: `student-${n}`,
          studentDisplayName: n === 1 ? "Amina Said" : "Omar Nabil",
          classId: "class-1",
          className: "Year 11 Physics",
          subjectCode: "0625",
          paperNumber: 2,
          paperVariant: 1,
          sessionMonth: "May",
          sessionYear: 2026,
          questionId: `3${n}`,
          reason: "low_confidence",
          status: "open",
          createdAt: "2026-11-12T08:00:00Z",
          waitingHours: 30,
          aiAwardedMarks: 2,
          maximumMarks: 3,
          confidenceScore: n === 1 ? 0.72 : 0.85,
        })
        await page.route("**/api/teacher/review?**", (route) =>
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ items: [item(1), item(2)], total: 2, nextCursor: null }),
          }),
        )
      },
    },
    async run(page) {
      const rows = page.locator(".lm-native-main a.lm-native-row")
      await rows.first().waitFor()
      if ((await rows.count()) !== 2) throw new Error(`expected 2 list rows, found ${await rows.count()}`)
      const hrefs = await rows.evaluateAll((els) => els.map((el) => el.getAttribute("href")))
      for (const want of ["/teacher/review/item-1", "/teacher/review/item-2"]) {
        if (!hrefs.some((h) => h === want || h?.startsWith(`${want}?`))) throw new Error(`no list row links to ${want}, got ${hrefs.join(", ")}`)
      }
      if ((await page.locator(".lm-native-main table").count()) !== 0) throw new Error("table rendered in list view")
      // List view: no bulk bar, and every row names why it is in the queue.
      if ((await page.getByRole("button", { name: /Bulk-approve/ }).count()) !== 0) throw new Error("Bulk-approve visible in list view")
      if ((await page.getByText("Select all", { exact: true }).count()) !== 0) throw new Error("Select all visible in list view")
      const lowConfidence = await page.locator(".lm-native-main a.lm-native-row", { hasText: "Low confidence" }).count()
      if (lowConfidence !== 2) throw new Error(`expected a reason chip on each of 2 list rows, found ${lowConfidence}`)
      await page.getByRole("button", { name: "View table" }).click()
      const region = tableRegion(page)
      await region.waitFor()
      const bodyRows = await region.locator("tbody tr").count()
      if (bodyRows !== 2) throw new Error(`expected 2 table body rows, found ${bodyRows}`)
      // Table view: the bulk bar is back; a selection made here must not survive a trip through the list.
      const bulk = page.getByRole("button", { name: /Bulk-approve/ })
      await bulk.waitFor()
      await region.locator("tbody input[type=checkbox]").first().check()
      await page.getByText("1 selected", { exact: true }).waitFor()
      await page.getByRole("button", { name: "View list" }).click()
      if ((await page.getByRole("button", { name: /Bulk-approve/ }).count()) !== 0) throw new Error("Bulk-approve still visible after switching to list")
      await page.getByRole("button", { name: "View table" }).click()
      await page.getByText("Select all", { exact: true }).waitFor()
      if ((await page.getByText(/\d+ selected/).count()) !== 0) throw new Error("selection survived a list round trip")
      // A failed bulk-approve must stay visible and announced after switching to the list.
      await page.route("**/api/teacher/review/bulk-approve", (route) =>
        route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) }),
      )
      await region.locator("tbody input[type=checkbox]").first().check()
      await page.getByRole("button", { name: /Bulk-approve/ }).click()
      await page.getByRole("alert").filter({ hasText: "Couldn't bulk-approve" }).waitFor()
      await page.getByRole("button", { name: "View list" }).click()
      const failure = page.getByRole("alert").filter({ hasText: "Couldn't bulk-approve" })
      if (!(await failure.isVisible())) throw new Error("bulk-approve error hidden after switching to list")
      if ((await failure.count()) !== 1) throw new Error("bulk-approve error not rendered once in list view")
      await page.getByRole("button", { name: "View table" }).click()
      // Reload: the table choice must come back from sessionStorage, not just a same-named region.
      await page.reload({ waitUntil: "networkidle" })
      await page.getByRole("button", { name: "View list" }).waitFor()
      const reloaded = tableRegion(page)
      await reloaded.waitFor()
      const afterRows = await reloaded.locator("tbody tr").count()
      if (afterRows !== 2) throw new Error(`after reload expected 2 table body rows, found ${afterRows}`)
      const listRows = await page.locator("a.lm-native-row").count()
      if (listRows !== 0) throw new Error(`after reload expected 0 list rows, found ${listRows}`)
      const stored = await page.evaluate(() => sessionStorage.getItem("lemely.review.view"))
      if (stored !== "table") throw new Error(`table choice not persisted, sessionStorage=${stored}`)
    },
  },
  ...[
    {
      id: "native-android-class-papers-list-and-table",
      surface: "class-papers",
      path: "/teacher/classes/class-1/papers",
      label: "Class papers",
      storageKey: "lemely.classPapers.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 2,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/classes\/class-1(\?|$)/, (route) => jsonRoute(route, CLASS_DETAIL))
        await page.route(/\/api\/classes\/class-1\/papers(\?|$)/, (route) =>
          jsonRoute(route, {
            papers: [
              classPaper(1, "Amina Said", false),
              classPaper(2, "Omar Nabil", true),
            ],
          }),
        )
      },
    },
    {
      id: "native-android-at-risk-list-and-table",
      surface: "at-risk",
      path: "/teacher/at-risk",
      label: "At-risk students",
      storageKey: "lemely.atRisk.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 3,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/teacher\/at-risk(\?|$)/, (route) => jsonRoute(route, AT_RISK_LIST(false)))
      },
    },
    {
      id: "native-android-mark-schemes-list-and-table",
      surface: "mark-schemes",
      path: "/teacher/schemes",
      label: "Mark schemes",
      storageKey: "lemely.markSchemes.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 2,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/schemes(\?|$)/, (route) =>
          jsonRoute(route, {
            schemes: [
              { doc: "0625_s24_ms_21.pdf", paper: "Paper 2 Variant 1", session: "May 2024", maxMarks: 80, questionCount: 9, status: "parsed" },
              { doc: "0625_w23_ms_41.pdf", paper: "Paper 4 Variant 1", session: "Nov 2023", maxMarks: null, questionCount: null, status: "pending" },
            ],
            stats: [],
          }),
        )
      },
    },
    {
      id: "native-android-classes-list-and-table",
      surface: "classes",
      path: "/teacher/classes",
      label: "Your classes",
      storageKey: "lemely.classes.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 3,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/teacher\/classes(\?|$)/, (route) => jsonRoute(route, { classes: CLASS_ROWS }))
      },
      async extra(page) {
        const text = await page.locator(".lm-native-main .lm-native-group").innerText()
        if (!/64% avg/.test(text)) throw new Error("average not labelled as an average")
        if (/—/.test(text)) throw new Error("stray dash in classes list")
        if (!/Subject not set/.test(text)) throw new Error("missing subject-not-set wording")
        if (!/tap View table/.test(await page.locator(".lm-native-main").innerText())) throw new Error("missing View table signpost")
        await expectNoMatch(page, "No classes match")
      },
    },
    {
      id: "native-android-quizzes-list-and-table",
      surface: "quizzes",
      path: "/teacher/quizzes",
      label: "Your quizzes",
      storageKey: "lemely.quizzes.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 2,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/teacher\/quizzes(\?|$)/, (route) => jsonRoute(route, { quizzes: QUIZ_ROWS }))
      },
      async extra(page) {
        await expectNoMatch(page, "No quizzes match")
      },
    },
    {
      id: "native-android-class-analytics-list-and-table",
      surface: "class-analytics",
      path: "/teacher/classes/class-1/analytics",
      label: "Per-paper comparison",
      storageKey: "lemely.analytics.papers.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 2,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/classes\/class-1(\?|$)/, (route) => jsonRoute(route, CLASS_DETAIL))
        await page.route(/\/api\/classes\/class-1\/analytics(\?|$)/, (route) => jsonRoute(route, ANALYTICS))
      },
      async extra(page) {
        await expectOneNameForGroup(page, "Per-paper comparison")
      },
    },
    {
      id: "native-android-student-detail-list-and-table",
      surface: "student-detail",
      path: "/teacher/students/s-yusuf",
      label: "Attempt history",
      storageKey: "lemely.studentAttempts.view",
      rowSelector: ".lm-native-main .lm-native-row",
      rows: 2,
      mocks: async (page) => {
        await teacherShellMocks(page)
        await page.route(/\/api\/teacher\/classes(\?|$)/, (route) => jsonRoute(route, { classes: CLASS_ROWS }))
        await page.route(/\/api\/teacher\/students\/s-yusuf(\?|$)/, (route) => jsonRoute(route, STUDENT))
      },
      async extra(page) {
        if ((await page.locator(".lm-native-main .lm-native-row button").count()) !== 0) throw new Error("attempt rows hold a button")
        if ((await page.locator(".lm-native-main .lm-native-group").getByText("Coming soon").count()) !== 0) throw new Error("Coming soon chip in attempt rows")
        const row = await page.locator(".lm-native-main .lm-native-row").first().innerText()
        if (!/44%/.test(row)) throw new Error(`trailing percentage missing: ${row}`)
        await expectOneNameForGroup(page, "Attempt history")
      },
    },
  ].map((c) => ({
    id: c.id,
    platform: "android",
    width: 390,
    app: { surface: "teacher-overview", state: "populated", path: c.path, mocks: c.mocks },
    async run(page) {
      await expectListThenTable(page, c)
      if (c.extra) {
        await page.getByRole("button", { name: "View list" }).click()
        await page.locator(c.rowSelector).first().waitFor()
        await c.extra(page)
      }
    },
  })),
  {
    id: "native-android-at-risk-acknowledge-from-list",
    platform: "android",
    width: 390,
    app: {
      surface: "teacher-overview",
      state: "populated",
      path: "/teacher/at-risk",
      mocks: async (page) => {
        await teacherShellMocks(page)
        let acknowledged = false
        await page.route(/\/api\/teacher\/at-risk(\?|$)/, (route) => jsonRoute(route, AT_RISK_LIST(acknowledged)))
        await page.route(/\/api\/teacher\/at-risk\/s-2\/acknowledge$/, async (route) => {
          const body = route.request().postDataJSON()
          if (body.reason !== "below_target" || body.note !== "Spoke to him") {
            return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "unexpected body" }) })
          }
          acknowledged = true
          return jsonRoute(route, { reason: "below_target", summary: "below_target", evidence: {}, acknowledged: { acknowledgedAt: "2026-11-13T09:00:00Z", note: "Spoke to him" } })
        })
      },
    },
    async run(page) {
      const rows = page.locator(".lm-native-main .lm-native-row")
      await rows.first().waitFor()
      if ((await page.locator(".lm-native-main .lm-native-row a button, .lm-native-main .lm-native-row button a").count()) !== 0) {
        throw new Error("interactive element nested inside another in a row")
      }
      const trigger = page.getByRole("button", { name: "Acknowledge flags for Omar Nabil" })
      const box = await trigger.boundingBox()
      if (!box || box.height < 48 || box.width < 48) throw new Error(`Android action target below 48px: ${JSON.stringify(box)}`)
      await trigger.click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      await dialog.getByRole("button", { name: "Acknowledge", exact: true }).click()
      await dialog.getByLabel(/Note/).fill("Spoke to him")
      await dialog.getByRole("button", { name: "Confirm acknowledge" }).click()
      // The refetched row, not the note: the textarea's own text matches "Spoke to him" the moment it is typed, so waiting on that proves nothing.
      await dialog.getByText(/^Acknowledged /).waitFor()
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      // The trigger is gone, so focus must land on the row's own link, not the page.
      const focused = await page.evaluate(() => {
        const a = document.activeElement
        return { tag: a?.tagName, text: a?.textContent ?? "" }
      })
      if (focused.tag !== "A" || !/Omar Nabil/.test(focused.text)) throw new Error(`focus not returned to the row link: ${JSON.stringify(focused)}`)
      const omar = rows.filter({ hasText: "Omar Nabil" })
      await omar.getByText(/Below target grade \(acknowledged\)/).waitFor()
      if ((await page.getByRole("button", { name: "Acknowledge flags for Omar Nabil" }).count()) !== 0) {
        throw new Error("Acknowledge still offered when every flag is acknowledged")
      }
      if ((await page.getByRole("button", { name: "Acknowledge flags for Amina Said" }).count()) !== 1) {
        throw new Error("Acknowledge missing on the row with unacknowledged flags")
      }
    },
  },
);

/** Reasons read in full: the three-reason student's subtitle is not clamped or truncated, on both platforms. */
const AT_RISK_REASONS_CHECKS = ["ios", "android"].map((platform) => ({
  id: `native-${platform}-at-risk-reasons-read-in-full`,
  platform,
  width: 390,
  app: {
    surface: "teacher-overview",
    state: "populated",
    path: "/teacher/at-risk",
    mocks: async (page) => {
      await teacherShellMocks(page)
      await page.route(/\/api\/teacher\/at-risk(\?|$)/, (route) => jsonRoute(route, AT_RISK_LIST(false)))
    },
  },
  async run(page) {
    const row = page.locator(".lm-native-main .lm-native-row", { hasText: "Layla Hassan" })
    await row.first().waitFor()
    const info = await row.first().evaluate((el) => {
      const sub = el.querySelector("a > span:nth-of-type(2) > span:nth-of-type(2)")
      const title = el.querySelector("a > span:nth-of-type(2) > span:nth-of-type(1)")
      return {
        text: sub?.textContent ?? "",
        subClipped: sub ? sub.scrollHeight > sub.clientHeight + 1 || sub.scrollWidth > sub.clientWidth + 1 : null,
        titleStart: title?.textContent ?? "",
      }
    })
    for (const label of ["Declining trend", "Below target grade", "Inactive"]) {
      if (!info.text.includes(label)) throw new Error(`reason missing from subtitle: ${label} (${info.text})`)
    }
    if (info.subClipped !== false) throw new Error(`reasons are truncated: ${JSON.stringify(info)}`)
    if (!info.titleStart.startsWith("Layla Hassan")) throw new Error(`name not leading the title: ${info.titleStart}`)
  },
}))
NATIVE_CHECKS.push(...AT_RISK_REASONS_CHECKS)

/** Type a search that matches nothing: a plain message, no fake row, no empty group. */
async function expectNoMatch(page, message) {
  await page.getByRole("searchbox").fill("zzz-no-such-thing")
  await page.getByText(message).waitFor()
  if ((await page.locator(".lm-native-main .lm-native-row").count()) !== 0) throw new Error(`${message}: a row rendered for the no-match state`)
  if ((await page.locator(".lm-native-main .lm-native-group").count()) !== 0) throw new Error(`${message}: an empty group rendered`)
  await page.getByRole("searchbox").fill("")
}

/** A section heading already names the group, so the group adds no second visible label. */
async function expectOneNameForGroup(page, name) {
  const labels = await page.locator(".lm-native-main .lm-native-group-label").filter({ hasText: name }).count()
  if (labels !== 0) throw new Error(`${name}: list group repeats the section heading`)
}

/** D11: two heading texts "repeat" when equal after these steps (see Task 5b). */
const normTitle = (s) => s.trim().toLowerCase().replace(/\s+/g, " ").replace(/^(your|my) /, "");

/** The `to` of each student bottom tab (STUDENT_BOTTOM_TABS in portals/student/shell.tsx)
 * minus the raised Correct action, which is immersive and has no tab root of its own. */
export const STUDENT_TAB_PATHS = ["/student", "/student/classes", "/student/profile"];
/** The `to` of each teacher bottom tab (TEACHER_BOTTOM_TABS in portals/teacher/index.tsx). */
export const TEACHER_TAB_PATHS = ["/teacher", "/teacher/grading", "/teacher/review", "/teacher/classes"];

/* Repeating screens left out because the mocks never reach their PageHeading (it renders only
 * after data the mocks do not serve, so the route would pass without checking anything):
 * student /subject/:code, /tutor-access, /recently-deleted; teacher /quizzes, /tutoring,
 * /tutoring/preview, /tutoring/profile, /tutoring/availability, /at-risk, /schemes,
 * /announcements, /deleted. /student/tutors and the tab roots stay as before. */
/** Tab roots of both portals plus the detail paths other checks use. Add a route
 * here when a screen's heading changes; skip only routes the mocks cannot serve,
 * with the reason in a comment. */
const HEADING_ROUTES = [
  ...[
    ...STUDENT_TAB_PATHS,
    DETAIL_PATH,
    "/student/tutors",
    "/student/notifications",
    "/student/sessions",
    "/student/correct",
  ].map((path) => ({ ...NATIVE_HOME, path })),
  ...[
    ...TEACHER_TAB_PATHS,
    TAB_DRILL_PATH,
    "/teacher/tutoring/students",
    "/teacher/notifications",
  ].map((path) => ({ ...NATIVE_TEACHER_HOME, path })),
];

NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) =>
    HEADING_ROUTES.map((app) => ({
      id: `native-${platform}-one-heading-${app.path}`,
      platform,
      width: 390,
      app,
      async run(page) {
        const h1s = await page.getByRole("heading", { level: 1 }).count();
        if (h1s !== 1)
          throw new Error(`${app.path}: ${h1s} level-1 headings reach assistive technology, expected 1`);
        const mainH1s = await page.locator("main").getByRole("heading", { level: 1 }).count();
        if (mainH1s !== 1)
          throw new Error(`${app.path}: ${mainH1s} level-1 headings inside <main>, expected 1`);
        const { title, headings } = await page.evaluate(() => ({
          title: document.querySelector("[data-shell-title]")?.textContent ?? "",
          headings: [...document.querySelectorAll("main :is(h1, h2, [role=heading])")]
            .filter((el) => {
              const r = el.getBoundingClientRect();
              return el.checkVisibility() && r.width > 1 && r.height > 1;
            })
            .map((el) => ({ text: el.textContent ?? "", html: el.outerHTML.slice(0, 120) })),
        }));
        const dupes = headings.filter((h) => normTitle(h.text) === normTitle(title));
        if (dupes.length)
          throw new Error(
            `${app.path}: visible heading repeats the large title: ${dupes.map((h) => h.html).join(" | ")}`,
          );
      },
    })),
  ),
);

/* ── Audit batch A (shell frame fixes). Each check is red on the tree before its fix. ── */

const rgb = (page, prop, selector) =>
  page.evaluate(([p, sel]) => getComputedStyle(document.querySelector(sel))[p], [prop, selector]);
/** The computed colour a token resolves to, via a throwaway probe. */
const tokenColour = (page, token) =>
  page.evaluate((t) => {
    const probe = document.createElement("i");
    probe.style.backgroundColor = `var(${t})`;
    document.body.appendChild(probe);
    const c = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return c;
  }, token);

NATIVE_CHECKS.push(
  // 1. Dark grouped surfaces.
  ...["ios", "android"].flatMap((platform) =>
    ["light", "dark"].map((theme) => ({
      id: `native-${platform}-${theme}-grouped-surface`,
      platform,
      theme,
      width: 390,
      app: NATIVE_HOME,
      async run(page) {
        const card = await rgb(page, "backgroundColor", "main .lm-native-card");
        const pageBg = await rgb(page, "backgroundColor", "[data-portal]");
        const want = await tokenColour(
          page,
          theme === "dark" ? "--md-surface-container-high" : "--md-surface-container-lowest",
        );
        if (card !== want) throw new Error(`${theme} card ${card}, preview surface-card ${want}`);
        if (card === pageBg) throw new Error(`${theme} card equals the page ground ${pageBg}`);
        if (theme === "dark") {
          const lum = (c) => c.match(/[\d.]+/g).slice(0, 3).reduce((a, b) => a + Number(b), 0);
          if (lum(card) <= lum(pageBg)) throw new Error(`dark card ${card} is not lighter than the page ${pageBg}`);
        }
      },
    })),
  ),
  // 2. Back control alignment.
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-back-centred`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: DETAIL_PATH },
    async run(page) {
      const align = await rgb(page, "alignItems", "header .lm-native-back");
      if (align !== "center") throw new Error(`back align-items ${align}`);
      const mid = await page.evaluate((plat) => {
        const back = document.querySelector("header .lm-native-back");
        const svg = back.querySelector(plat === "ios" ? ".lm-native-back-ios" : ".lm-native-back-md");
        const r = svg.getBoundingClientRect();
        const b = back.getBoundingClientRect();
        const out = { svg: r.y + r.height / 2, back: b.y + b.height / 2 };
        const label = back.querySelector(".lm-native-back-label");
        if (plat === "ios") {
          const l = label.getBoundingClientRect();
          out.label = l.y + l.height / 2;
          out.gap = getComputedStyle(back).columnGap;
        }
        return out;
      }, platform);
      if (Math.abs(mid.svg - mid.back) > 1) throw new Error(`glyph centre ${mid.svg} vs button ${mid.back}`);
      if (platform === "ios") {
        if (Math.abs(mid.svg - mid.label) > 1.5) throw new Error(`chevron ${mid.svg} vs label ${mid.label}`);
        if (mid.gap !== "2px") throw new Error(`iOS chevron-label gap ${mid.gap}, expected 2px`);
      }
    },
  })),
  // 3. Heading hierarchy on roots.
  ...["ios", "android"].flatMap((platform) =>
    [
      ["student", NATIVE_HOME],
      ["teacher", NATIVE_TEACHER_HOME],
    ].map(([who, app]) => ({
      id: `native-${platform}-${who}-own-heading-steps-down`,
      platform,
      width: 390,
      app,
      async run(page) {
        const h = await page.evaluate(() => {
          const el = document.querySelector('main [data-page-heading="own"]');
          const large = document.querySelector("[data-shell-large-title]");
          return el && { fs: parseFloat(getComputedStyle(el).fontSize), large: parseFloat(getComputedStyle(large).fontSize), text: el.textContent };
        });
        if (!h) throw new Error("no own-text page heading on the root");
        if (h.fs > 28) throw new Error(`"${h.text}" is ${h.fs}px, expected at most 28px`);
        if (h.fs >= h.large) throw new Error(`own heading ${h.fs}px is not below the large title ${h.large}px`);
      },
    })),
  ),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-section-heading-leaves-card`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const r = await page.evaluate(() => {
        const h = [...document.querySelectorAll("main h2")].find((e) => /Subjects this session/i.test(e.textContent));
        if (!h) return null;
        const s = getComputedStyle(h);
        const big = [...document.querySelectorAll("main .lm-native-card h2")].filter((e) => parseFloat(getComputedStyle(e).fontSize) >= 28).length;
        return { inCard: !!h.closest(".lm-native-card"), transform: s.textTransform, family: s.fontFamily, fs: parseFloat(s.fontSize), big };
      });
      if (!r) throw new Error("section heading not found");
      if (r.inCard) throw new Error("section heading still sits inside its card");
      if (r.transform !== "uppercase" || !/mono/i.test(r.family)) throw new Error(`section label style ${r.transform} / ${r.family}`);
      if (r.big) throw new Error(`${r.big} display-size headings still inside native cards`);
    },
  })),
  {
    id: "native-other-section-heading-stays-in-card",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const inCard = await page.evaluate(() => {
        const h = [...document.querySelectorAll("main h2")].find((e) => /Subjects this session/i.test(e.textContent));
        return h && { inCard: !!h.closest(".lm-native-card"), fs: parseFloat(getComputedStyle(h).fontSize) };
      });
      if (!inCard?.inCard || inCard.fs !== 32) throw new Error(`desktop-style heading changed: ${JSON.stringify(inCard)}`);
    },
  },
  // 4. Left/right safe areas.
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-safe-area-inline`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 0, bottom: 0, left: 40, right: 36 } });
      await page.waitForTimeout(100);
      const got = await page.evaluate(() => {
        const pad = (sel) => {
          const s = getComputedStyle(document.querySelector(sel));
          return [parseFloat(s.paddingLeft), parseFloat(s.paddingRight)];
        };
        return { main: pad("main"), bar: pad("header[data-title-level]"), tabs: pad("nav.lm-native-tabbar"), large: pad("[data-shell-large-title]") };
      });
      for (const [name, [l, r]] of Object.entries(got)) {
        if (l < 40 || r < 36) throw new Error(`${name} padding ${l}/${r} does not clear the 40/36 side insets`);
      }
    },
  })),
  // 5. iOS bar gap.
  ...[["student", NATIVE_HOME], ["teacher", NATIVE_TEACHER_HOME]].map(([who, app]) => ({
    id: `native-ios-${who}-bar-gap-zero-title-clear`,
    platform: "ios",
    width: 390,
    app,
    async run(page) {
      const gap = await rgb(page, "columnGap", "header[data-title-level]");
      if (gap !== "0px") throw new Error(`bar column-gap ${gap}, expected 0px`);
      await page.evaluate(() => window.scrollTo(0, 100000));
      await page.waitForFunction(() => document.querySelector("header[data-title-level]").dataset.collapsed === "true");
      const r = await page.evaluate(() => {
        const t = document.querySelector("header [data-shell-title]").getBoundingClientRect();
        const first = [...document.querySelectorAll("header[data-title-level] :is(a, button)")]
          .filter((e) => e.checkVisibility()).map((e) => e.getBoundingClientRect()).sort((a, b) => a.x - b.x)[0];
        return { right: t.right, left: t.left, firstAction: first.x, width: innerWidth };
      });
      if (r.right > r.firstAction + 0.5) throw new Error(`title box ends at ${r.right}, first action starts at ${r.firstAction}`);
      if (Math.abs((r.left + r.right) / 2 - r.width / 2) > 1) throw new Error(`collapsed title is not centred on screen (${r.left}-${r.right})`);
    },
  })),
  // 6. Android back arrow colour.
  {
    id: "native-android-back-arrow-on-surface",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: DETAIL_PATH },
    async run(page) {
      const back = await rgb(page, "color", "header .lm-native-back");
      const want = await page.evaluate(() => {
        const probe = document.createElement("i");
        probe.style.color = "var(--md-on-surface)";
        document.body.appendChild(probe);
        const c = getComputedStyle(probe).color;
        probe.remove();
        return c;
      });
      if (back !== want) throw new Error(`back arrow ${back}, expected on-surface ${want}`);
    },
  },
  // 15. Back label cap.
  {
    id: "native-ios-back-label-capped",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: DETAIL_PATH },
    async run(page) {
      const r = await page.evaluate(() => {
        const label = document.querySelector("header .lm-native-back-label");
        label.textContent = "A parent page with a very long title that must truncate";
        const s = getComputedStyle(label);
        return { w: label.getBoundingClientRect().width, max: s.maxWidth, overflow: s.textOverflow };
      });
      if (r.max !== "96px" || r.overflow !== "ellipsis" || r.w > 96.5) throw new Error(`back label ${JSON.stringify(r)}`);
    },
  },
  // 7 and 8. Edge-to-edge containers and Android grouped content.
  ...["ios", "android"].flatMap((platform) =>
    [
      ["student", NATIVE_HOME, ["Momentum", "Weakest threads"]],
      ["teacher", NATIVE_TEACHER_HOME, ["What fills in as you add more"]],
    ].map(([who, app, headings]) => ({
      id: `native-${platform}-${who}-containers-are-native-cards`,
      platform,
      width: 390,
      app,
      async run(page) {
        const res = await page.evaluate((titles) => {
          return titles.map((t) => {
            const h = [...document.querySelectorAll("main :is(h2, h3)")].find((e) => e.textContent.trim().startsWith(t));
            const card = h?.closest(".lm-native-card");
            const r = card?.getBoundingClientRect();
            return { t, card: !!card, x: r && Math.round(r.x), w: r && Math.round(r.width), found: !!h };
          });
        }, headings);
        for (const c of res) {
          if (!c.found) throw new Error(`heading "${c.t}" not found`);
          if (!c.card) throw new Error(`"${c.t}" container is not an lm-native-card`);
          if (platform === "android" && (c.x !== 0 || c.w !== 390)) throw new Error(`"${c.t}" card is not full-bleed (${c.x}, ${c.w})`);
          if (platform === "ios" && (c.x !== 16 || c.w !== 358)) throw new Error(`"${c.t}" card is not inset-grouped (${c.x}, ${c.w})`);
        }
        const steps = who === "teacher" ? await page.locator("main ol > li.lm-native-card").count() : 1;
        if (!steps) throw new Error("teacher setup steps are not native cards");
      },
    })),
  ),
  {
    id: "native-android-card-content-16px-no-dividers",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const r = await page.evaluate(() => {
        const rows = [...document.querySelectorAll("main .lm-native-card > .lm-native-card-row")];
        const insets = rows.map((row) => Math.round(row.firstElementChild.getBoundingClientRect().left));
        const borders = [...document.querySelectorAll("main .lm-native-card > *")]
          .map((e) => getComputedStyle(e))
          .filter((s) => parseFloat(s.borderTopWidth) > 0 || parseFloat(s.borderBottomWidth) > 0).length;
        return { insets, borders, rows: rows.length };
      });
      if (!r.rows) throw new Error("no in-card rows found");
      if (r.insets.some((x) => x !== 16)) throw new Error(`row content starts at ${r.insets} px, expected 16`);
      if (r.borders) throw new Error(`${r.borders} in-card dividers remain on Android`);
    },
  },
  // 9. Android tab label baseline.
  {
    id: "native-android-tab-labels-one-baseline",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student" },
    async run(page) {
      const ys = await page.evaluate(() =>
        [...document.querySelectorAll("nav.lm-native-tabbar .lm-native-tab-label")].map((e) => Math.round(e.getBoundingClientRect().bottom * 10) / 10),
      );
      if (new Set(ys).size !== 1) throw new Error(`tab labels sit at different baselines: ${ys}`);
    },
  },
  // 10. Active-tab re-tap.
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-tab-retap-drilled-scrolled-pops-back`,
    platform,
    width: 390,
    app: { ...NATIVE_TEACHER_HOME, path: TAB_DRILL_PATH },
    async run(page) {
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px";
        window.scrollTo(0, 600);
      });
      await page.waitForFunction(() => window.scrollY > 100);
      await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Classes" }).click();
      await page.waitForURL(/\/teacher\/classes$/);
      const dir = await page.evaluate(() => document.documentElement.dataset.direction);
      if (dir !== "back") throw new Error(`pop to root reads as ${dir}, expected back`);
    },
  })),
  {
    id: "native-ios-tab-retap-at-root-scrolls-not-navigates",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_TEACHER_HOME, path: "/teacher/classes" },
    async run(page) {
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px";
        window.scrollTo(0, 600);
      });
      await page.waitForFunction(() => window.scrollY > 100);
      await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Classes" }).click();
      await page.waitForFunction(() => window.scrollY === 0);
      if (new URL(page.url()).pathname !== "/teacher/classes") throw new Error("a tap at the root navigated");
    },
  },
  // 11. Sheet drag from content.
  {
    id: "native-ios-sheet-drags-from-content",
    platform: "ios",
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const trigger = page.getByRole("button", { name: "Create" }).filter({ visible: true }).first();
      await trigger.click();
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      const title = dialog.locator("h2");
      const box = await title.boundingBox();
      const x = box.x + box.width / 2;
      // An upward move from the body is the body's scroll: the sheet must not follow.
      await page.mouse.move(x, box.y + 4);
      await page.mouse.down();
      await page.mouse.move(x, box.y - 40, { steps: 4 });
      if (await dialog.evaluate((el) => el.hasAttribute("data-dragging"))) throw new Error("an upward move dragged the sheet");
      await page.mouse.up();
      // A mouse drag across text selects it, and pressing on a selection starts the browser's own drag.
      await page.evaluate(() => getSelection()?.removeAllRanges());
      // A downward move from the body at scrollTop 0 drags it, with no transition lag, and a long one dismisses.
      await page.mouse.move(x, box.y + 4);
      await page.mouse.down();
      await page.mouse.move(x, box.y + 4 + 70, { steps: 6 });
      const mid = await dialog.evaluate((el) => ({ dragging: el.hasAttribute("data-dragging"), translate: el.style.translate }));
      if (!mid.dragging) throw new Error("a downward move from the body did not start a drag");
      const dy = parseFloat(mid.translate.split(" ")[1]);
      if (!(dy > 50 && dy <= 70)) throw new Error(`sheet follows the finger by ${mid.translate}, expected about 64px`);
      await page.mouse.move(x, box.y + 500, { steps: 8 });
      await page.mouse.up();
      await dialog.waitFor({ state: "detached" });
    },
  },
);

/** The routes a phone's tab bar already holds, per portal; More must not repeat them. */
const TAB_TARGETS = {
  student: ["/student", "/student/classes", "/student/profile", "/student/correct"],
  teacher: ["/teacher", "/teacher/grading", "/teacher/review", "/teacher/classes"],
};

NATIVE_CHECKS.push(
  // 12 and 17. More is a titled sheet of overflow destinations, with popup semantics.
  ...["ios", "android"].flatMap((platform) =>
    [
      ["student", NATIVE_HOME],
      ["teacher", NATIVE_TEACHER_HOME],
    ].map(([who, app]) => ({
      id: `native-${platform}-${who}-more-is-a-titled-sheet`,
      platform,
      width: 390,
      app,
      async run(page) {
        // A CSS locator: an open dialog marks the page behind it aria-hidden, which hides the button from role queries.
        const more = page.locator("nav.lm-native-tabbar button[aria-haspopup]");
        if ((await more.getAttribute("aria-haspopup")) !== "dialog") throw new Error("More lacks aria-haspopup=dialog");
        if ((await more.getAttribute("aria-expanded")) !== "false") throw new Error("More lacks aria-expanded=false when closed");
        await more.click();
        const dialog = page.getByRole("dialog", { name: "More" });
        await dialog.waitFor();
        if ((await more.getAttribute("aria-expanded")) !== "true") throw new Error("More is not aria-expanded=true while open");
        if (!(await dialog.locator(".lm-sheet-grabber").count()) && !(await page.locator(".lm-sheet [role=dialog], [role=dialog].lm-sheet").count()))
          throw new Error("More is not a bottom sheet");
        const hrefs = await dialog.locator("a").evaluateAll((els) => els.map((e) => new URL(e.href).pathname));
        if (!hrefs.length) throw new Error("More lists no destinations");
        const dupes = hrefs.filter((h) => TAB_TARGETS[who].includes(h.replace(/\/$/, "")));
        if (dupes.length) throw new Error(`More repeats tab bar destinations ${dupes}`);
        await dialog.locator("a").first().click();
        await dialog.waitFor({ state: "detached" });
        if (new URL(page.url()).pathname !== hrefs[0]) throw new Error(`row went to ${page.url()}, not ${hrefs[0]}`);
      },
    })),
  ),
  {
    id: "native-other-768-more-keeps-the-drawer",
    width: 768,
    app: NATIVE_HOME,
    async run(page) {
      const more = page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "More" });
      await more.click();
      await page.getByRole("dialog").waitFor();
      if (await page.locator(".lm-sheet").count()) throw new Error("tablet opened a bottom sheet");
      if ((await more.getAttribute("aria-expanded")) !== "true") throw new Error("More is not aria-expanded while the drawer is open");
    },
  },
  // 13. The bar's inline title is hidden from assistive technology.
  {
    id: "native-ios-bar-title-aria-hidden",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if ((await page.locator("header [data-shell-title]").getAttribute("aria-hidden")) !== "true")
        throw new Error("the bar title is exposed twice with the page h1");
    },
  },
  // 14. RTL badge.
  {
    id: "native-ios-tab-badge-follows-rtl",
    platform: "ios",
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const measure = () =>
        page.evaluate(() => {
          const badge = document.querySelector("nav.lm-native-tabbar [class*='bg-error']");
          const icon = badge.closest(".lm-native-tab-icon");
          const b = badge.getBoundingClientRect();
          const i = icon.getBoundingClientRect();
          return { badgeLeft: b.left, badgeRight: b.right, iconLeft: i.left, iconRight: i.right };
        });
      const ltr = await measure();
      if (!(ltr.badgeRight > ltr.iconRight)) throw new Error(`LTR badge ${JSON.stringify(ltr)} is not at the end`);
      await page.evaluate(() => (document.documentElement.dir = "rtl"));
      const rtl = await measure();
      if (!(rtl.badgeLeft < rtl.iconLeft)) throw new Error(`RTL badge ${JSON.stringify(rtl)} did not move to the end side`);
    },
  },
  // 16. Teacher Create leaves the phone bar.
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-teacher-create-leaves-the-bar`,
    platform,
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const inBar = await page.locator("header[data-title-level] :is(a, button)").evaluateAll((els) =>
        els.filter((e) => e.checkVisibility()).map((e) => e.getAttribute("aria-label") || e.textContent.trim()),
      );
      if (inBar.some((n) => /^Create/.test(n))) throw new Error(`Create is still in the bar: ${inBar}`);
      if (inBar.length > 3) throw new Error(`${inBar.length} trailing icons in the bar: ${inBar}`);
      if (platform === "android") {
        if (await page.locator(".lm-native-large-action").count()) throw new Error("Android renders the iOS large-title plus");
        const fab = page.locator(".lm-native-fab");
        if (!(await fab.isVisible())) throw new Error("no FAB on the teacher root");
        const r = await page.evaluate(() => {
          const f = document.querySelector(".lm-native-fab");
          const t = document.querySelector("nav.lm-native-tabbar").getBoundingClientRect();
          const b = f.getBoundingClientRect();
          const probe = document.createElement("i");
          probe.style.backgroundColor = "var(--md-primary-container)";
          document.body.appendChild(probe);
          const want = getComputedStyle(probe).backgroundColor;
          probe.remove();
          return { h: b.height, right: innerWidth - b.right, above: t.top - b.bottom, bg: getComputedStyle(f).backgroundColor, want, text: f.textContent.trim(), radius: getComputedStyle(f).borderRadius };
        });
        if (r.h !== 56) throw new Error(`FAB is ${r.h}px high, expected 56`);
        if (r.text !== "Create") throw new Error(`extended FAB label "${r.text}"`);
        if (Math.round(r.right) !== 16 || Math.round(r.above) !== 16) throw new Error(`FAB sits ${r.right}px from the end and ${r.above}px above the tab bar, expected 16 and 16`);
        if (r.bg !== r.want) throw new Error(`FAB background ${r.bg}, expected primary container ${r.want}`);
        await fab.click();
      } else {
        const plus = page.locator(".lm-native-large-action button");
        if (!(await plus.isVisible())) throw new Error("no + in the large-title row");
        const place = await page.evaluate(() => {
          const p = document.querySelector(".lm-native-large-action button").getBoundingClientRect();
          const l = document.querySelector("[data-shell-large-title]").getBoundingClientRect();
          return { within: p.y + p.height / 2 > l.y && p.y + p.height / 2 < l.bottom, end: innerWidth - p.right, w: p.width };
        });
        if (!place.within) throw new Error("the + is not in the large-title row");
        if (place.w !== 44) throw new Error(`the + is ${place.w}px wide, expected 44`);
        await page.evaluate(() => window.scrollTo(0, 100000));
        await page.waitForFunction(() => document.querySelector("header[data-title-level]").dataset.collapsed === "true");
        if (await plus.isVisible()) throw new Error("the + stays after the large title collapses");
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForFunction(() => document.querySelector("header[data-title-level]").dataset.collapsed === "false");
        await plus.click();
      }
      const dialog = page.getByRole("dialog");
      await dialog.waitFor();
      const sheet = await page.evaluate((plat) => {
        const d = document.querySelector("[role=dialog]");
        const h = d.querySelector("h2");
        const s = getComputedStyle(h);
        const eyebrow = [...d.querySelectorAll("p")].filter((p) => p.checkVisibility() && /^create$/i.test(p.textContent.trim())).length;
        return { fs: s.fontSize, fw: s.fontWeight, eyebrow, text: h.textContent };
      }, platform);
      if (sheet.eyebrow) throw new Error("the mono CREATE eyebrow still shows on a native sheet");
      const want = platform === "ios" ? ["17px", "600"] : ["22px", "400"];
      if (sheet.fs !== want[0] || sheet.fw !== want[1]) throw new Error(`sheet title ${sheet.fs}/${sheet.fw}, expected ${want}`);
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      const focused = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") || document.activeElement?.textContent?.trim());
      if (!/^Create/.test(focused ?? "")) throw new Error(`focus returned to "${focused}", not the opener`);
    },
  })),
  {
    id: "native-ios-teacher-detail-has-no-create",
    platform: "ios",
    width: 390,
    app: NATIVE_TEACHER_DETAIL,
    async run(page) {
      if (await page.locator(".lm-native-large-action, .lm-native-fab").count()) throw new Error("a detail page offers Create");
    },
  },
  {
    id: "native-android-student-has-no-fab",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if (await page.locator(".lm-native-fab").count()) throw new Error("the student root has a FAB");
    },
  },
  {
    id: "native-other-desktop-keeps-create-in-bar",
    width: 1440,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const create = page.locator("header[data-title-level]").getByRole("button", { name: "Create" });
      if (!(await create.isVisible())) throw new Error("desktop lost the bar's Create button");
      if (await page.locator(".lm-native-fab").isVisible()) throw new Error("desktop shows the FAB");
    },
  },
);

/* ── Audit A, Impeccable pass: M3 FAB scroll behaviour, full-inset bleed, flat More list. ── */
NATIVE_CHECKS.push(
  {
    id: "native-android-fab-shrinks-on-scroll-down-extends-on-up",
    platform: "android",
    width: 390,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const fab = page.locator(".lm-native-fab");
      const width = () => fab.evaluate((el) => Math.round(el.getBoundingClientRect().width));
      if ((await width()) <= 56) throw new Error("the FAB is not extended at the top");
      await page.evaluate(() => {
        document.body.style.minHeight = "3000px";
        window.scrollTo(0, 400);
      });
      await page.waitForFunction(() => document.querySelector(".lm-native-fab").getBoundingClientRect().width <= 56);
      await page.evaluate(() => window.scrollTo(0, 300));
      await page.waitForFunction(() => document.querySelector(".lm-native-fab").getBoundingClientRect().width > 56);
    },
  },
  {
    id: "native-android-cards-bleed-to-the-edge-under-side-insets",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send("Emulation.setSafeAreaInsetsOverride", { insets: { top: 0, bottom: 0, left: 40, right: 36 } });
      await page.waitForTimeout(100);
      const r = await page.evaluate(() => {
        const card = document.querySelector("main .lm-native-card").getBoundingClientRect();
        const row = document.querySelector("main .lm-native-card > .lm-native-card-row").firstElementChild.getBoundingClientRect();
        return { x: Math.round(card.x), w: Math.round(card.width), content: Math.round(row.left) };
      });
      if (r.x !== 0 || r.w !== 390) throw new Error(`card ${r.x}/${r.w} does not reach both screen edges under insets`);
      if (r.content < 40) throw new Error(`content starts at ${r.content}, inside the 40px inset`);
    },
  },
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-more-list-is-flat-in-the-sheet`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("nav.lm-native-tabbar button[aria-haspopup]").click();
      const dialog = page.getByRole("dialog", { name: "More" });
      await dialog.waitFor();
      const r = await dialog.evaluate((el) => {
        const g = el.querySelector("[data-list-group]");
        const row = el.querySelector("[data-lines]");
        return { border: getComputedStyle(g).borderTopWidth, h: Math.round(row.getBoundingClientRect().height), radius: getComputedStyle(g).borderTopLeftRadius };
      });
      if (r.border !== "0px") throw new Error(`More list keeps the desktop outline (${r.border})`);
      if (platform === "android" && (r.h < 56 || r.radius !== "0px")) throw new Error(`Android More rows ${r.h}px / radius ${r.radius}, expected 56dp flat`);
      if (platform === "ios" && (r.h < 44 || r.radius !== "12px")) throw new Error(`iOS More rows ${r.h}px / radius ${r.radius}, expected 44pt inset-grouped`);
    },
  })),
);
NATIVE_CHECKS.push(
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-press-state`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      // Press the element, read its computed state while held, release, read again.
      const press = async (loc, dx, dy) => {
        await loc.waitFor()
        await loc.evaluate((el) => el.scrollIntoView({ block: "center" }))
        const box = await loc.boundingBox()
        await page.mouse.move(box.x + dx, box.y + dy)
        await page.mouse.down()
        const pressed = await loc.evaluate((el) => {
          const cs = getComputedStyle(el)
          return {
            flag: el.hasAttribute("data-pressed"),
            image: cs.backgroundImage,
            scale: cs.scale,
            overflow: cs.overflow,
            x: el.style.getPropertyValue("--lm-press-x"),
            r: cs.getPropertyValue("--lm-press-r"),
            rr: cs.getPropertyValue("--lm-press-rr"),
            opacity: cs.opacity,
          }
        })
        // Release away from the element so the tap never becomes a click and navigates.
        await page.mouse.move(2, 300)
        await page.mouse.up()
        const released = await loc.evaluate((el) => ({ flag: el.hasAttribute("data-pressed"), image: getComputedStyle(el).backgroundImage }))
        return { pressed, released }
      }
      const expectScale = platform === "ios" ? "0.97" : "none"
      // The header icon button, then a Button primitive: the Button also carries the web
      // `active:scale-[0.98]`, which native must cancel (iOS owns 0.97, Android never scales).
      const targets = [
        { name: "icon button", loc: page.locator("header .lm-native-iconbtn.lm-press:visible").first(), dx: 14, dy: 14 },
        // The tab cell: dims on iOS with no delay (it is a fixed bar, not scroll content), never scales.
        { name: "tab cell", loc: page.locator("nav.lm-native-tabbar .lm-press:visible").nth(1), dx: 14, dy: 14, tab: true },
        { name: "Button", loc: page.locator("main .lm-press-scale:not(.lm-native-iconbtn):visible").first(), dx: 10, dy: 10 },
      ]
      for (const t of targets) {
        const { pressed, released } = await press(t.loc, t.dx, t.dy)
        if (!pressed.flag) throw new Error(`${t.name}: data-pressed not set on pointerdown`)
        if (t.tab && platform === "ios" && pressed.opacity !== "0.55") throw new Error(`${t.name}: iOS tab opacity ${pressed.opacity} right after pointerdown, expected 0.55`)
        if (t.tab && platform === "ios") {
          if (released.flag || released.image !== "none") throw new Error(`${t.name}: press state stuck after pointerup`)
          if (pressed.scale !== "none") throw new Error(`${t.name}: iOS tab scale ${pressed.scale}, expected none`)
          continue
        }
        if (!pressed.image.includes("radial-gradient")) throw new Error(`${t.name}: no press layer: ${pressed.image}`)
        if (pressed.overflow === "hidden") throw new Error(`${t.name}: press layer clips with overflow: hidden`)
        if (Math.abs(parseFloat(pressed.x) - t.dx) > 3) throw new Error(`${t.name}: ripple origin x ${pressed.x}, expected ${t.dx}px`)
        if (pressed.scale !== (t.tab ? "none" : expectScale)) throw new Error(`${t.name}: ${platform} press scale ${pressed.scale}, expected ${t.tab ? "none" : expectScale}`)
        if (platform === "android" && (!pressed.r || pressed.rr !== pressed.r)) throw new Error(`${t.name}: ripple radius ${pressed.rr}, expected ${pressed.r}`)
        if (released.flag || released.image !== "none") throw new Error(`${t.name}: press state stuck after pointerup`)
      }
      if (platform === "android") {
        // The ripple animation is frozen by the harness, so the runtime proof is that the
        // keyframes exist and resolve; the ripple radius above proves the end state.
        const hasKeyframes = await page.evaluate(() =>
          [...document.styleSheets].some((sheet) => {
            try { return [...sheet.cssRules].some((r) => r.type === CSSRule.KEYFRAMES_RULE && r.name === "lm-ripple") } catch { return false }
          }),
        )
        if (!hasKeyframes) throw new Error("lm-ripple keyframes missing from document.styleSheets")
      }
    },
  })),
)

/* Task 13: the shell's pull-to-refresh (D6). A mouse drag drives the same pointer events a finger does. */

/** A point inside the pull surface that is not an interactive control, so the pull's start filter accepts it. */
async function pullStart(page) {
  const point = await page.evaluate(() => {
    const main = document.querySelector(".lm-ptr");
    const r = main.getBoundingClientRect();
    const interactive = "a,button,input,select,textarea,summary,[role=button],[role=link],[tabindex]:not([tabindex=\"-1\"])";
    for (let y = Math.max(r.top, 0) + 8; y < Math.min(r.bottom, window.innerHeight) - 8; y += 8) {
      for (let x = 60; x < window.innerWidth - 60; x += 24) {
        const el = document.elementFromPoint(x, y);
        if (el && main.contains(el) && !el.closest(interactive)) return { x, y };
      }
    }
    return null;
  });
  if (!point) throw new Error("no non-interactive point to start a pull from");
  return point;
}

async function pullDown(page, dy, { release = true } = {}) {
  const { x, y } = await pullStart(page);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + dy, { steps: 12 });
  if (release) await page.mouse.up();
}

/** Holds every `/api/` request for `holdMs` (so a refresh stays in flight) and counts them. */
async function countApi(page, holdMs = 0) {
  const seen = { calls: 0 };
  await page.route("**/api/**", async (route) => {
    seen.calls++;
    if (holdMs) await new Promise((r) => setTimeout(r, holdMs));
    return route.fallback();
  });
  return seen;
}

/** Counts requests matching one endpoint glob; the later `page.route` runs first and `fallback()` hands the request to the scene's mock. */
async function countEndpoint(page, glob) {
  const seen = { calls: 0 };
  await page.route(glob, (route) => {
    seen.calls++;
    return route.fallback();
  });
  return seen;
}

/* Each root's own data endpoint, the one its scene mocks: a refetch of anything else (the notification
   badge, a review count) must not satisfy the check. */
for (const [id, app, platform, glob] of [
  ["native-android-pull-to-refresh-refetches", NATIVE_HOME, "android", "**/api/student/overview"],
  ["native-ios-pull-to-refresh-refetches", NATIVE_HOME, "ios", "**/api/student/overview"],
  ["native-android-teacher-pull-to-refresh-refetches", NATIVE_TEACHER_HOME, "android", "**/api/teacher/overview"],
]) {
  NATIVE_CHECKS.push({
    id,
    platform,
    width: 390,
    app,
    async run(page) {
      await page.locator("main").waitFor();
      await page.waitForTimeout(400);
      const seen = await countEndpoint(page, glob);
      await pullDown(page, 200);
      await page.waitForTimeout(600);
      if (seen.calls < 1) throw new Error(`pull did not refetch the page's own endpoint (${glob})`);
    },
  });
}

/** The computed `translate` of a selector, as a Y offset in px (0 for `none`). */
const translateY = (page, selector) =>
  page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const t = getComputedStyle(el).translate;
    return t === "none" ? 0 : parseFloat(t.split(" ")[1]) || 0;
  }, selector);

NATIVE_CHECKS.push(
  {
    id: "native-ios-pull-content-follows-and-holds",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("main").waitFor();
      await page.waitForTimeout(400);
      await countApi(page, 1500);
      await pullDown(page, 40, { release: false });
      await page.waitForTimeout(150);
      const mid = await translateY(page, ".lm-ptr-content");
      if (mid === null || Math.abs(mid - 40) > 1) throw new Error(`content should follow the finger 1:1 to 40px, got ${mid}`);
      if ((await page.locator(".lm-ptr-ios").count()) !== 1) throw new Error("iOS 8-spoke indicator missing");
      await page.mouse.up();
      await page.waitForTimeout(500);
      await pullDown(page, 200);
      await page.waitForFunction(() => document.querySelector(".lm-ptr")?.dataset.ptr === "refreshing");
      await page.waitForTimeout(100);
      const hold = await translateY(page, ".lm-ptr-content");
      if (Math.abs(hold - 56) > 1) throw new Error(`content should hold 56px while refreshing, got ${hold}`);
    },
  },
  {
    id: "native-android-pull-disc-moves-content-stays",
    platform: "android",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("main").waitFor();
      await page.waitForTimeout(400);
      await countApi(page, 1500);
      await pullDown(page, 40, { release: false });
      await page.waitForTimeout(150);
      const content = await translateY(page, ".lm-ptr-content");
      if (content !== 0) throw new Error(`Android content must stay still, got ${content}px`);
      const disc = await translateY(page, ".lm-ptr-gap");
      if (disc === null || Math.abs(disc - 40) > 1) throw new Error(`disc should be 40px down, got ${disc}`);
      await page.mouse.up();
      await page.waitForTimeout(500);
      await pullDown(page, 200);
      await page.waitForFunction(() => document.querySelector(".lm-ptr")?.dataset.ptr === "refreshing");
      await page.waitForTimeout(100);
      const hold = await translateY(page, ".lm-ptr-gap");
      if (Math.abs(hold - 64) > 1) throw new Error(`disc should hold 64px while refreshing, got ${hold}`);
      if ((await translateY(page, ".lm-ptr-content")) !== 0) throw new Error("content moved while refreshing on Android");
    },
  },
  {
    id: "native-android-wide-has-no-shell-pull",
    platform: "android",
    width: 800,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("main").waitFor();
      await page.waitForTimeout(400);
      if ((await page.locator(".lm-ptr").count()) !== 0) throw new Error("a 721px+ android window must not get the native pull surface");
      if ((await page.locator(".lm-ptr-gap").count()) !== 0) throw new Error("a 721px+ android window must not render the pull indicator");
      // A drag from the top of the page must not move anything either.
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      await page.mouse.move(400, 300);
      await page.mouse.down();
      await page.mouse.move(400, 500, { steps: 10 });
      const moved = await page.evaluate(() => [...document.querySelectorAll("main, main > *")].some((el) => {
        const t = getComputedStyle(el).translate;
        return (t !== "none" && t !== "0px") || (el.style.transform && el.style.transform !== "none");
      }));
      await page.mouse.up();
      if (moved) throw new Error("a 721px+ android drag moved the page");
      const overscroll = await page.evaluate(() => [document.documentElement, document.body, document.querySelector("main")].map((el) => el.style.overscrollBehaviorY).join("|"));
      if (overscroll !== "||") throw new Error(`no overscroll style may be set at 721px+, got "${overscroll}"`);
    },
  },
  {
    id: "native-other-has-no-shell-pull",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.locator("main").waitFor();
      if ((await page.locator(".lm-ptr").count()) !== 0) throw new Error("the platform other must not get the native pull surface");
    },
  },
);

// Native frame Task 12: interactive edge swipe-back. Standalone display on both platforms (D5);
// browser tabs keep the platform's own gesture. Playwright cannot set display-mode, so an init
// script fakes navigator.standalone and stubs the display-mode media query.
const STANDALONE = () => {
  Object.defineProperty(navigator, "standalone", { value: true })
  const real = window.matchMedia.bind(window)
  window.matchMedia = (q) =>
    q.includes("display-mode: standalone")
      ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} }
      : real(q)
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-standalone-swipe-back",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 4 })
      if (!(await page.evaluate(() => document.documentElement.hasAttribute("data-swiping"))))
        throw new Error("drag did not start an interactive swipe")
      await page.mouse.move(200, 404, { steps: 6 })
      await page.mouse.up()
      await page.waitForURL(/\/student$/)
    },
  },
  {
    id: "native-ios-swipe-short-cancels",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE },
    async run(page) {
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 20 })
      // Rest past the 100ms velocity window so the release is slow and short: 56px of 390.
      await page.waitForTimeout(250)
      await page.mouse.up()
      // The harness zeroes motion, so no transitionend fires; the hook's 600ms fallback clears the spring.
      await page.waitForTimeout(900)
      if (!/\/student\/classes/.test(page.url())) throw new Error("a short slow swipe navigated")
      const left = await page.evaluate(() => ({
        swiping: document.documentElement.hasAttribute("data-swiping"),
        transform: document.querySelector("[data-shell-column]")?.style.transform ?? "",
        transition: document.querySelector("[data-shell-column]")?.style.transition ?? "",
      }))
      if (left.swiping) throw new Error("data-swiping stayed set after a cancelled swipe")
      if (left.transform || left.transition) throw new Error(`column not sprung home: ${JSON.stringify(left)}`)
    },
  },
  {
    id: "native-ios-swipe-fling-commits-below-distance",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(30, 401)
      await page.waitForTimeout(8)
      // 80px is under the 35% distance (136px of 390); only the fling can commit it.
      await page.mouse.move(80, 402)
      await page.mouse.up()
      await page.waitForURL(/\/student$/, { timeout: 3000 })
    },
  },
  {
    id: "native-android-standalone-swipe-back",
    platform: "android",
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(60, 402, { steps: 4 })
      if (!(await page.evaluate(() => document.documentElement.hasAttribute("data-swiping"))))
        throw new Error("Android standalone did not start an interactive swipe (D5 keeps it)")
      await page.mouse.move(250, 404, { steps: 6 })
      await page.mouse.up()
      await page.waitForURL(/\/student$/)
    },
  },
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-browser-tab-no-swipe-back`,
    platform,
    // No STANDALONE init: a browser tab, where Safari's swipe and Chrome's back take over.
    app: { ...NATIVE_HOME, path: "/student" },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(250, 402, { steps: 6 })
      const swiping = await page.evaluate(() => document.documentElement.hasAttribute("data-swiping"))
      await page.mouse.up()
      await page.waitForTimeout(400)
      if (swiping || !/\/student\/classes/.test(page.url())) throw new Error("the in-app swipe-back ran in a browser tab")
    },
  })),
  {
    id: "native-ios-swipe-keeps-text-selectable",
    platform: "ios",
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE },
    async run(page) {
      const sel = await page.evaluate(() => getComputedStyle(document.querySelector("main")).userSelect)
      if (sel === "none") throw new Error("content lost text selection")
    },
  },
);

// Fix round 1: the swipe underlay paints only inside the native frame (phone width, iOS or Android).
const underlayPaints = (page) =>
  page.evaluate(() => {
    const before = getComputedStyle(document.body, "::before")
    const column = document.querySelector("[data-shell-column]")
    return {
      content: before.content,
      shadow: column ? getComputedStyle(column).boxShadow : "no-column",
    }
  })
async function dragIntoSwipe(page) {
  await page.getByRole("link", { name: "Classes" }).first().click()
  await page.waitForURL(/\/student\/classes/)
  await page.mouse.move(4, 400)
  await page.mouse.down()
  await page.mouse.move(60, 402, { steps: 4 })
  if (!(await page.evaluate(() => document.documentElement.hasAttribute("data-swiping")))) throw new Error("drag did not start a swipe")
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-swipe-underlay-paints-in-frame",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await dragIntoSwipe(page)
      const got = await underlayPaints(page)
      await page.mouse.up()
      if (got.content === "none" || got.shadow === "none") throw new Error(`underlay missing in the frame: ${JSON.stringify(got)}`)
    },
  },
  {
    id: "native-ios-swipe-underlay-silent-at-tablet",
    platform: "ios",
    width: 800,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await dragIntoSwipe(page)
      const got = await underlayPaints(page)
      await page.mouse.up()
      if (got.content !== "none" || got.shadow !== "none") throw new Error(`underlay painted at 800px: ${JSON.stringify(got)}`)
    },
  },
  {
    id: "native-other-swipe-underlay-silent",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await dragIntoSwipe(page)
      const got = await underlayPaints(page)
      await page.mouse.up()
      if (got.content !== "none" || got.shadow !== "none") throw new Error(`underlay painted on other: ${JSON.stringify(got)}`)
    },
  },
);

// Fix round 2: a committed swipe continues the gesture (no snap to x=0), and a cancel fades with the slide.
// The probe records the column in the same task as the hook's pointerup handler (a window bubble listener
// runs after the handler on <html>), then once per frame, so a snap to 0 on release cannot hide.
const SWIPE_PROBE = () => {
  const root = document.documentElement
  const snap = () => {
    const c = document.querySelector("[data-shell-column]")
    const num = (name) => parseFloat(getComputedStyle(root).getPropertyValue(name)) || 0
    return {
      t: performance.now(),
      left: c ? Math.round(c.getBoundingClientRect().left * 10) / 10 : null,
      inline: c ? c.style.transform : null,
      swiping: root.hasAttribute("data-swiping"),
      progress: num("--lm-swipe-progress"),
      shadow: num("--lm-swipe-shadow"),
      // View-transition pseudo-element animations running right now (RR 7 replays one on a pop).
      vt: document.getAnimations().filter((a) => a.playState === "running" && String(a.effect?.pseudoElement ?? "").startsWith("::view-transition")).length,
    }
  }
  const probe = { before: 0, release: null, frames: [] }
  window.__swipeProbe = probe
  window.addEventListener("pointermove", () => {
    probe.before = snap().left
  })
  window.addEventListener("pointerup", () => {
    probe.release = snap()
    const start = performance.now()
    const tick = () => {
      probe.frames.push(snap())
      if (performance.now() - start < 800) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}
async function swipeBackWithProbe(page, { fling, deepLink = false }) {
  if (!deepLink) {
    // A pushed entry, so the swipe takes the history path (navigate(-1)); a deep link takes the replace path.
    await page.getByRole("link", { name: "Classes" }).first().click()
    await page.waitForURL(/\/student\/classes/)
  }
  await page.evaluate(SWIPE_PROBE)
  await page.mouse.move(4, 400)
  await page.mouse.down()
  if (fling) {
    await page.mouse.move(100, 401, { steps: 4 })
    await page.mouse.move(210, 402, { steps: 3 })
  } else {
    await page.mouse.move(210, 402, { steps: 8 })
    await page.waitForTimeout(150)
  }
  await page.mouse.up()
  await page.waitForTimeout(900)
  return page.evaluate(() => window.__swipeProbe)
}
function assertContinues(probe, minOffset = 100) {
  if (!probe.release) throw new Error("no pointerup was observed")
  if (!(probe.before > minOffset)) throw new Error(`drag never offset the column (before ${probe.before})`)
  if (!(probe.release.left >= probe.before - 0.5))
    throw new Error(`the column snapped on release: ${probe.before}px before, ${probe.release.left}px right after (inline "${probe.release.inline}")`)
  if (probe.release.swiping !== true) throw new Error("the swipe state was dropped in the release frame")
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-swipe-commit-continues-gesture",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      const probe = await swipeBackWithProbe(page, { fling: false })
      assertContinues(probe)
      if (!/\/student$/.test(page.url())) throw new Error("the swipe did not navigate")
    },
  },
  {
    id: "native-ios-swipe-commit-animates-off-screen",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      const probe = await swipeBackWithProbe(page, { fling: false })
      assertContinues(probe)
      const width = 390
      const frames = probe.frames
      const home = frames.findIndex((f) => f.left !== null && f.left < probe.before - 1)
      const travel = frames.slice(0, home === -1 ? frames.length : home)
      if (travel.length < 3) throw new Error(`commit did not animate: ${travel.length} frames of travel`)
      for (let i = 1; i < travel.length; i++)
        if (travel[i].left < travel[i - 1].left - 0.5) throw new Error(`the column moved back during the exit: ${JSON.stringify(travel.map((f) => f.left))}`)
      if (!travel.some((f) => f.left > probe.before + 1 && f.left < width - 1)) throw new Error("no intermediate frame: the exit jumped")
      if (!travel.some((f) => f.progress > probe.release.progress + 0.02 && f.progress < 0.98)) throw new Error("the dim did not fade over the slide")
      if (travel.at(-1).left < width - 12) throw new Error(`the column stopped short of the edge: ${travel.at(-1).left}`)
      if (!/\/student$/.test(page.url())) throw new Error("the swipe did not navigate")
      const rest = frames.at(-1)
      if (rest.left !== 0 || rest.swiping || rest.inline) throw new Error(`state left over after the swipe: ${JSON.stringify(rest)}`)
    },
  },
  {
    id: "native-ios-swipe-fling-commit-is-faster-than-drag",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      const exitMs = (probe) => {
        const end = probe.frames.find((f) => f.left !== null && f.left >= 378)
        if (!end) throw new Error("the column never reached the edge")
        return end.t - probe.release.t
      }
      const flung = exitMs(await swipeBackWithProbe(page, { fling: true }))
      if (flung > 260) throw new Error(`a fling took ${Math.round(flung)}ms to leave`)
    },
  },
  {
    id: "native-ios-swipe-cancel-fades-with-slide",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/classes", init: STANDALONE, motion: true },
    async run(page) {
      await page.evaluate(SWIPE_PROBE)
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(70, 402, { steps: 10 })
      await page.waitForTimeout(250)
      await page.mouse.up()
      await page.waitForTimeout(900)
      const probe = await page.evaluate(() => window.__swipeProbe)
      if (!/\/student\/classes/.test(page.url())) throw new Error("a short slow swipe navigated")
      assertContinues(probe, 30)
      const f = probe.frames
      const cleared = f.findIndex((x) => !x.swiping)
      if (cleared === -1) throw new Error("data-swiping never cleared")
      if (cleared < 3) throw new Error(`the swipe state cleared after ${cleared} frames: it must last the slide home`)
      if (f[cleared].left > 1) throw new Error(`swipe state cleared with the column ${f[cleared].left}px from home`)
      const slide = f.slice(0, cleared)
      if (!slide.some((x) => x.shadow > 0.02 && x.shadow < 0.98)) throw new Error("the shadow did not fade with the slide")
      if (!slide.some((x) => x.progress > 0.02 && x.progress < probe.release.progress - 0.02)) throw new Error("the dim did not fade with the slide")
      for (let i = 1; i < slide.length; i++)
        if (slide[i].left > slide[i - 1].left + 0.5) throw new Error("the column overshot on cancel (iOS curve has no overshoot)")
    },
  },
  {
    // The one-shot flag must be read on every navigation. Two swipes in a row replace to the same
    // path (no navigation-type change); a stale flag then leaks into the next tab tap.
    id: "native-ios-swipe-flag-does-not-go-stale",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/settings/devices", init: STANDALONE },
    async run(page) {
      const direction = () => page.evaluate(() => document.documentElement.dataset.direction)
      const swipe = async () => {
        await page.mouse.move(4, 400)
        await page.mouse.down()
        await page.mouse.move(230, 402, { steps: 8 })
        await page.mouse.up()
        await page.waitForTimeout(500)
      }
      await swipe()
      if ((await direction()) !== "swipe") throw new Error(`first swipe read "${await direction()}"`)
      await swipe()
      if ((await direction()) !== "swipe") throw new Error(`second swipe read "${await direction()}"`)
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      // The URL moves before React renders the new route; give the layout effect its turn.
      await page.waitForFunction(() => document.documentElement.dataset.direction !== "swipe", null, { timeout: 1500 }).catch(() => {})
      if ((await direction()) !== "forward") throw new Error(`a tab tap read "${await direction()}": the swipe flag went stale`)
    },
  },
);

// Fix round 3: one animation per committed hop; cancellable navigation; input lock; guard.
const maxVt = (probe) => Math.max(0, ...probe.frames.map((f) => f.vt))
NATIVE_CHECKS.push(
  ...[
    ["history", {}, "/student"],
    ["replace", { deepLink: true }, "/student/classes"],
  ].flatMap(([name, opts, path]) => [
    {
      id: `native-ios-swipe-commit-${name}-path-plays-no-view-transition`,
      platform: "ios",
      width: 390,
      app: { ...NATIVE_HOME, path, init: STANDALONE, motion: true },
      async run(page) {
        const probe = await swipeBackWithProbe(page, { fling: false, ...opts })
        assertContinues(probe)
        if (!/\/student$/.test(page.url())) throw new Error("the swipe did not navigate")
        if (maxVt(probe) > 0) throw new Error(`${maxVt(probe)} view-transition animation(s) ran after the column left (a second slide)`)
      },
    },
    {
      id: `native-ios-swipe-reduced-motion-${name}-path-plays-no-view-transition`,
      platform: "ios",
      width: 390,
      app: { ...NATIVE_HOME, path, init: STANDALONE },
      async run(page) {
        const probe = await swipeBackWithProbe(page, { fling: false, ...opts })
        if (maxVt(probe) > 0) throw new Error(`${maxVt(probe)} view-transition animation(s) ran under reduced motion`)
        if (!/\/student$/.test(page.url())) throw new Error("the swipe did not navigate")
      },
    },
  ]),
  {
    // A plain browser-back pop under reduced motion: RR 7 replays the reverse transition; the app's
    // reduced-motion rule must silence it.
    id: "native-ios-pop-reduced-motion-plays-no-view-transition",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student" },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      await page.waitForTimeout(400)
      await page.evaluate(() => {
        window.__vtMax = 0
        const start = performance.now()
        const tick = () => {
          const n = document.getAnimations().filter((a) => a.playState === "running" && String(a.effect?.pseudoElement ?? "").startsWith("::view-transition")).length
          window.__vtMax = Math.max(window.__vtMax, n)
          if (performance.now() - start < 800) requestAnimationFrame(tick)
        }
        requestAnimationFrame(tick)
      })
      await page.goBack()
      await page.waitForTimeout(900)
      const max = await page.evaluate(() => window.__vtMax)
      if (max > 0) throw new Error(`a pop played ${max} view-transition animation(s) under reduced motion`)
      if (!/\/student$/.test(page.url())) throw new Error("goBack did not pop")
    },
  },
);

/** Start a committed history-path swipe and run `during` ~60ms into the slide. */
async function swipeThenDuringSlide(page, during) {
  await page.getByRole("link", { name: "Classes" }).first().click()
  await page.waitForURL(/\/student\/classes/)
  await page.waitForTimeout(300)
  await page.mouse.move(4, 400)
  await page.mouse.down()
  await page.mouse.move(210, 402, { steps: 8 })
  await page.waitForTimeout(150)
  await page.mouse.up()
  await page.waitForTimeout(60)
  await during()
  await page.waitForTimeout(1200)
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-swipe-history-back-mid-slide-pops-once",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      await swipeThenDuringSlide(page, () => page.evaluate(() => history.back()))
      if (new URL(page.url()).pathname !== "/student") throw new Error(`two pops: ended on ${page.url()}`)
    },
  },
  {
    id: "native-ios-swipe-tab-tap-mid-slide-is-ignored",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      const box = await page.getByRole("link", { name: "Profile" }).first().boundingBox()
      await swipeThenDuringSlide(page, () => page.mouse.click(box.x + box.width / 2, box.y + box.height / 2))
      if (new URL(page.url()).pathname !== "/student") throw new Error(`a tap during the commit slide moved the page: ${page.url()}`)
    },
  },
  {
    id: "native-ios-swipe-navigation-mid-slide-is-not-popped-back",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      // A programmatic click skips the input lock, isolating the cancellable navigation.
      await swipeThenDuringSlide(page, () =>
        page.evaluate(() => [...document.querySelectorAll("a")].find((a) => a.getAttribute("href") === "/student/profile")?.click()),
      )
      if (new URL(page.url()).pathname !== "/student/profile") throw new Error(`the stale swipe navigation popped the page back: ${page.url()}`)
    },
  },
  {
    id: "native-ios-swipe-guard-keeps-column-off-screen",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      await page.getByRole("link", { name: "Classes" }).first().click()
      await page.waitForURL(/\/student\/classes/)
      // The router never reports: the guard fires with the commit still pending.
      await page.evaluate(() => {
        history.go = () => {}
      })
      await page.mouse.move(4, 400)
      await page.mouse.down()
      await page.mouse.move(210, 402, { steps: 8 })
      await page.waitForTimeout(150)
      await page.mouse.up()
      await page.waitForTimeout(1900)
      const got = await page.evaluate(() => ({
        swiping: document.documentElement.hasAttribute("data-swiping"),
        transform: document.querySelector("[data-shell-column]")?.style.transform ?? "",
        left: document.querySelector("[data-shell-column]")?.getBoundingClientRect().left,
        lock: getComputedStyle(document.body).pointerEvents,
      }))
      if (got.swiping) throw new Error("the dim and shadow outlived the guard")
      if (got.lock === "none") throw new Error("the input lock outlived the guard")
      if (!got.transform || got.left < 300) throw new Error(`the guard handed the old page back: ${JSON.stringify(got)}`)
    },
  },
);

/* Task 7. The ConfirmModal call site is the student Account and devices tab's "Sign out
   everywhere" (AccountSettings.tsx), served by studentShellMocks. The Modal call site is
   the report sheet on a student tutor profile (TutorProfile.tsx > ReportSheet), a
   dismissible Modal; the profile and its side requests are stubbed below. */
const TUTOR_ID = "tutor-amira"
const TUTOR_PROFILE = {
  tutorId: TUTOR_ID,
  publicName: "Amira K.",
  headline: "IGCSE Maths and Physics",
  subjects: [{ code: "0580", name: "Mathematics" }],
  modes: ["virtual"],
  area: { code: "alexandria", name: "Alexandria" },
  rating: { state: "new", average: null, count: 0 },
  bio: "Five years of tutoring.",
  qualificationNote: null,
  otherModeNote: null,
  documentsSeen: true,
  availability: [],
  zone: "Africa/Cairo",
  zoneLabel: "Cairo time",
  listedSince: "2026-01",
}
const json = (route, body, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
const tutorProfileMocks = async (page) => {
  await studentShellMocks("populated")(page)
  await page.route(`**/api/tutors/${TUTOR_ID}/**`, (route) => json(route, { items: [], nextCursor: null }))
  await page.route(`**/api/tutors/${TUTOR_ID}/outcomes`, (route) =>
    json(route, { tutorId: TUTOR_ID, ladder: [], duringWindowDays: 90, beforeLookbackDays: 90, subjects: [] }),
  )
  await page.route(`**/api/tutors/${TUTOR_ID}`, (route) => json(route, TUTOR_PROFILE))
  await page.route("**/api/student/tutor-grants", (route) => json(route, { items: [] }))
}

NATIVE_CHECKS.push(
  {
    id: "native-ios-confirm-is-action-sheet",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/settings/devices" },
    async run(page) {
      const trigger = page.getByRole("button", { name: "Sign out everywhere" }).first()
      // The button stays disabled until the devices request settles; name that step if it never does.
      await trigger.waitFor().then(() => page.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => b.textContent === "Sign out everywhere" && !b.disabled), null, { timeout: 15000 })).catch((e) => { throw new Error(`trigger never enabled: ${e.message.split("\n")[0]}`) })
      await trigger.click()
      const dialog = page.getByRole("dialog", { name: "Sign out everywhere?" })
      await dialog.waitFor()
      if (!(await dialog.evaluate((el) => el.classList.contains("lm-action-sheet")))) throw new Error("not an action sheet")
      // Modal moves focus in on the next frame; an Escape sent before that lands on the settings panel underneath.
      // Focus must land on Cancel, never the destructive row that comes first in DOM order.
      await page.waitForFunction(() => document.activeElement?.matches(".lm-action-sheet [data-autofocus]"), null, { timeout: 5000 }).catch(() => { throw new Error("focus did not land on the Cancel row") })
      const focused = await page.evaluate(() => ({ cancel: document.activeElement?.classList.contains("lm-action-sheet-cancel"), label: document.activeElement?.textContent }))
      if (!focused.cancel || focused.label !== "Stay signed in") throw new Error(`focus is on "${focused.label}", not the Cancel row`)
      // The Cancel group sits apart from the destructive group, with room below it.
      const gaps = await dialog.evaluate((el) => {
        const group = el.querySelector(".lm-action-sheet-group").getBoundingClientRect()
        const cancel = el.querySelector(".lm-action-sheet-cancel").getBoundingClientRect()
        return { gap: cancel.top - group.bottom, below: window.innerHeight - cancel.bottom }
      })
      if (gaps.gap < 8) throw new Error(`group to Cancel gap is ${gaps.gap}px, expected at least 8`)
      if (gaps.below < 8) throw new Error(`Cancel sits ${gaps.below}px above the screen edge, expected at least 8`)
      if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" })
      await page.keyboard.press("Escape")
      // isVisible() stays true for the whole exit animation, so also require no data-closing after it would have started.
      await page.waitForTimeout(400)
      if (!(await dialog.isVisible()) || (await dialog.evaluate((el) => el.hasAttribute("data-closing")))) throw new Error("Escape answered a destructive question")
      await dialog.getByRole("button", { name: "Stay signed in" }).click()
      await dialog.waitFor({ state: "detached" })
    },
  },
  {
    id: "native-android-modal-back-closes",
    platform: "android",
    width: 390,
    app: { ...NATIVE_HOME, path: `/student/tutors/${TUTOR_ID}`, mocks: tutorProfileMocks },
    async run(page) {
      await page.getByRole("button", { name: "Report", exact: true }).click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      if (!(await dialog.evaluate((el) => el.classList.contains("lm-sheet")))) throw new Error("Modal is not a sheet on native")
      await page.goBack()
      await dialog.waitFor({ state: "detached" })
    },
  },
)

NATIVE_CHECKS.push(
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-bell-sheet`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const bell = page.getByRole("button", { name: /^Notifications/ })
      await bell.click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      if (!(await dialog.evaluate((el) => el.classList.contains("lm-sheet")))) throw new Error("the bell panel is not a sheet")
      if ((await page.getByRole("menu").count()) !== 0) throw new Error("native bell still opens a menu")
      if ((await dialog.locator(".lm-list-row").count()) === 0) throw new Error("the bell sheet has no grouped rows")
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      if (!(await bell.evaluate((el) => el === document.activeElement))) throw new Error("focus not returned to the bell")
    },
  })),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-account-sheet`,
    platform,
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      const avatar = page.getByRole("button", { name: /^Your profile and account/ })
      await avatar.click()
      const dialog = page.getByRole("dialog", { name: "Account" })
      await dialog.waitFor()
      if ((await page.getByRole("menu").count()) !== 0) throw new Error("native avatar still opens a menu")
      for (const name of ["Your profile", "Sign out"])
        if ((await dialog.getByText(name, { exact: true }).count()) === 0) throw new Error(`the account sheet has no ${name} row`)
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      if (!(await avatar.evaluate((el) => el === document.activeElement))) throw new Error("focus not returned to the avatar")
    },
  })),
  ...["ios", "android"].map((platform) => ({
    // The settings sections sit in the native group look inside the sheet, which portals outside <main>.
    id: `native-${platform}-settings-sheet-groups`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/settings" },
    async run(page) {
      const dialog = page.getByRole("dialog", { name: "Settings" })
      await dialog.waitFor()
      const m = await dialog.evaluate((el) => {
        const group = el.querySelector(".lm-native-group")
        if (!group) return null
        const g = group.getBoundingClientRect()
        const s = el.getBoundingClientRect()
        const cs = getComputedStyle(group)
        return { radius: cs.borderTopLeftRadius, border: cs.borderTopWidth, left: g.left - s.left, right: s.right - g.right }
      })
      if (!m) throw new Error("no .lm-native-group in the settings sheet")
      if (m.border !== "0px") throw new Error(`group keeps its outline (${m.border})`)
      if (platform === "ios" && (m.radius !== "12px" || Math.abs(m.left - 16) > 0.5 || Math.abs(m.right - 16) > 0.5))
        throw new Error(`iOS inset group wrong: radius ${m.radius}, margins ${m.left}/${m.right}`)
      if (platform === "android" && (m.radius !== "0px" || Math.abs(m.left) > 0.5 || Math.abs(m.right) > 0.5))
        throw new Error(`Android group not full-bleed: radius ${m.radius}, margins ${m.left}/${m.right}`)
    },
  })),
  {
    id: "native-ios-settings-sheet-back-closes",
    platform: "ios",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      await page.getByRole("link", { name: "Settings" }).click()
      const dialog = page.getByRole("dialog", { name: "Settings" })
      await dialog.waitFor()
      const depth = () => page.evaluate(() => document.documentElement.hasAttribute("data-sheet-depth"))
      if (await depth()) throw new Error("settings opened at large; the preview opens it at medium")
      const grab = await dialog.locator(".lm-sheet-grabber").boundingBox()
      await page.mouse.move(grab.x + grab.width / 2, grab.y + 2)
      await page.mouse.down()
      await page.mouse.move(grab.x + grab.width / 2, grab.y - 300, { steps: 8 })
      await page.mouse.up()
      await page.waitForFunction(() => document.documentElement.hasAttribute("data-sheet-depth"))
      await page.goBack()
      await dialog.waitFor({ state: "detached" })
      if (new URL(page.url()).pathname !== "/student") throw new Error("back did not return to the page")
      if (await depth()) throw new Error("the page stayed scaled back after the sheet closed")
    },
  },
)

// A row tap navigates first, and the sheet closes when the location changes. Closing first would have
// useDialogHistory unwind with navigate(-1) before the destination's push landed (a lazy route or reduced
// motion), so the tap went nowhere. Every lazy chunk requested after load is held back below, so the
// destination always arrives after the close would have. The Back, idx and orphan checks that follow live
// in the dialog-exit group further down.
const SHEET_NAV_CASES = [
  {
    id: "bell-row",
    to: "/student/announcements",
    async open(page) {
      await page.getByRole("button", { name: /^Notifications/ }).click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      return { dialog, row: dialog.getByRole("button", { name: /Physics mock moved/ }) }
    },
  },
  {
    id: "bell-footer",
    to: "/student/notifications",
    async open(page) {
      await page.getByRole("button", { name: /^Notifications/ }).click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      return { dialog, row: dialog.getByRole("link", { name: "All notifications" }) }
    },
  },
  {
    id: "account-row",
    to: "/student/parents",
    async open(page) {
      await page.getByRole("button", { name: /^Your profile and account/ }).click()
      const dialog = page.getByRole("dialog", { name: "Account" })
      await dialog.waitFor()
      return { dialog, row: dialog.getByRole("link", { name: "Your parents" }) }
    },
  },
]

NATIVE_CHECKS.push(
  ...SHEET_NAV_CASES.flatMap((c) =>
    ["reduce", "no-preference"].map((motion) => ({
      id: `native-ios-sheet-nav-${c.id}-${motion === "reduce" ? "reduced-motion" : "motion"}`,
      platform: "ios",
      width: 390,
      app: NATIVE_HOME,
      async run(page) {
        await page.emulateMedia({ reducedMotion: motion })
        await page.route(/\/assets\/[^/]+\.js(\?|$)/, async (route) => {
          await new Promise((resolve) => setTimeout(resolve, 600))
          await route.continue()
        })
        const { dialog, row } = await c.open(page)
        await row.click()
        await page.waitForURL((url) => url.pathname === c.to, { timeout: 8000 })
        await dialog.waitFor({ state: "detached" })
        await page.waitForTimeout(400)
        if (new URL(page.url()).pathname !== c.to) throw new Error(`the tap went nowhere: ${new URL(page.url()).pathname}`)
        await page.goBack()
        await page.waitForURL((url) => url.pathname === "/student", { timeout: 5000 })
        if ((await page.getByRole("dialog").count()) !== 0) throw new Error("a dialog came back after Back")
      },
    })),
  ),
)

/* Task 9. Popover is a sheet on native. The Notifications row is one of three call sites: a long
   press on an unread card opens its "Mark read" popover (studentShellMocks "populated" has unread rows). */
NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) => ["light", "dark"].map((theme) => ({
  id: `native-${platform}-popover-is-sheet${theme === "dark" ? "-dark" : ""}`,
  platform,
  theme,
  width: 390,
  app: { ...NATIVE_HOME, path: "/student/notifications" },
  async run(page) {
    const card = page.locator("main h2").first().locator("xpath=ancestor::div[@tabindex='-1'][1]")
    await card.waitFor()
    const box = await card.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + 8)
    await page.mouse.down()
    await page.waitForTimeout(700)
    await page.mouse.up()
    const dialog = page.getByRole("dialog")
    await dialog.waitFor().catch(() => { throw new Error("long press opened no dialog") })
    if (!(await dialog.evaluate((el) => el.classList.contains("lm-sheet")))) throw new Error("the popover is not a sheet on native")
    await page.waitForFunction(() => document.activeElement?.closest(".lm-sheet"), null, { timeout: 5000 }).catch(() => { throw new Error("focus did not move into the sheet") })
    if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH.replace(".png", `-${platform}-${theme}.png`), animations: "disabled" })
    await page.keyboard.press("Escape")
    await dialog.waitFor({ state: "detached" })
    if (!(await card.evaluate((el) => el === document.activeElement))) throw new Error("focus not returned to the trigger")
  },
  }))),
)

/* Task 8b. A row tap inside a dialog REPLACES the dialog's history entry, so the history reads
   [origin, destination] and one Back returns to the origin. A push past the entry leaves an orphan:
   [origin, dialog, destination], whose second Back is a dead press. Proven by react-router's own
   history.state.idx, which is the origin's idx + 1 at the destination only without the orphan. */
const histIdx = (page) => page.evaluate(() => window.history.state?.idx ?? 0)

async function runDialogExit(page, { open, to }) {
  const origin = new URL(page.url())
  const originIdx = await histIdx(page)
  const { dialog, row } = await open(page)
  await row.click()
  await page.waitForURL((url) => url.pathname === to, { timeout: 8000 })
  await dialog.waitFor({ state: "detached" })
  await page.waitForTimeout(400)
  const idx = await histIdx(page)
  if (idx !== originIdx + 1) throw new Error(`orphan dialog entry: destination idx ${idx}, expected ${originIdx + 1}`)
  await page.goBack()
  await page.waitForURL((url) => url.pathname === origin.pathname, { timeout: 5000 })
  if ((await page.getByRole("dialog").count()) !== 0) throw new Error("a dialog came back after Back")
  if ((await histIdx(page)) !== originIdx) throw new Error(`Back landed on idx ${await histIdx(page)}, expected the origin ${originIdx}`)
  // The second Back must leave the origin (a URL change, or an idx decrease): not a dead press.
  await page.goBack()
  await page.waitForTimeout(500)
  const left = page.url() !== origin.href || (await histIdx(page)) < originIdx
  if (!left) throw new Error("the second Back was a dead press: the origin never changed")
}

const MORE_ROW_CASE = {
  id: "more-row",
  to: null,
  async open(page) {
    await page.locator("nav.lm-native-tabbar button[aria-haspopup]").click()
    const dialog = page.getByRole("dialog", { name: "More" })
    await dialog.waitFor()
    return { dialog, row: dialog.locator("a").first() }
  },
}

NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) =>
    [...SHEET_NAV_CASES, MORE_ROW_CASE].map((c) => ({
      id: `native-${platform}-dialog-exit-${c.id}-one-back-to-origin`,
      platform,
      width: 390,
      app: NATIVE_HOME,
      async run(page) {
        let to = c.to
        if (!to) {
          // The More sheet's first destination, read from the open sheet.
          await page.locator("nav.lm-native-tabbar button[aria-haspopup]").click()
          const dialog = page.getByRole("dialog", { name: "More" })
          await dialog.waitFor()
          to = new URL(await dialog.locator("a").first().evaluate((a) => a.href)).pathname
          await page.keyboard.press("Escape")
          await dialog.waitFor({ state: "detached" })
          await page.waitForTimeout(400)
        }
        await runDialogExit(page, { open: c.open, to })
      },
    })),
  ),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-dialog-exit-same-path-row-leaves-no-entry`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: "/student/notifications" },
    async run(page) {
      const originIdx = await histIdx(page)
      await page.getByRole("button", { name: /^Notifications/ }).click()
      const dialog = page.getByRole("dialog", { name: "Notifications" })
      await dialog.waitFor()
      await dialog.getByRole("link", { name: "All notifications" }).click()
      await dialog.waitFor({ state: "detached" })
      await page.waitForTimeout(400)
      if (new URL(page.url()).pathname !== "/student/notifications") throw new Error("a same-path row changed the URL")
      const idx = await histIdx(page)
      if (idx !== originIdx) throw new Error(`same-path row left idx ${idx}, expected ${originIdx}`)
      if ((await page.getByRole("dialog").count()) !== 0) throw new Error("the dialog stayed open")
    },
  })),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-dialog-exit-modal-close-unwinds-once`,
    platform,
    width: 390,
    app: { ...NATIVE_HOME, path: `/student/tutors/${TUTOR_ID}`, mocks: tutorProfileMocks },
    async run(page) {
      const originIdx = await histIdx(page)
      await page.getByRole("button", { name: "Report", exact: true }).click()
      const dialog = page.getByRole("dialog")
      await dialog.waitFor()
      if ((await histIdx(page)) !== originIdx + 1) throw new Error("opening the modal did not push exactly one entry")
      await page.keyboard.press("Escape")
      await dialog.waitFor({ state: "detached" })
      await page.waitForTimeout(500)
      const idx = await histIdx(page)
      if (idx !== originIdx) throw new Error(`Modal close left idx ${idx}, expected ${originIdx} (double or missed unwind)`)
    },
  })),
  {
    id: "native-other-768-dialog-exit-drawer-row-one-back-to-origin",
    width: 768,
    app: NATIVE_TEACHER_HOME,
    async run(page) {
      const origin = new URL(page.url())
      let to = null
      await runDialogExit(page, {
        to: await (async () => {
          const more = page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "More" })
          await more.click()
          const dialog = page.getByRole("dialog")
          await dialog.waitFor()
          const hrefs = await dialog.getByRole("link").evaluateAll((els) => els.map((e) => new URL(e.href).pathname))
          to = hrefs.find((h) => h !== origin.pathname)
          await page.keyboard.press("Escape")
          await dialog.waitFor({ state: "detached" })
          await page.waitForTimeout(400)
          return to
        })(),
        async open(p) {
          await p.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "More" }).click()
          const dialog = p.getByRole("dialog")
          await dialog.waitFor()
          return { dialog, row: dialog.locator(`a[href="${to}"]`).first() }
        },
      })
    },
  },
)

/* ── Audit batch B (sheets, confirms, review and roster lists). Each check is red on the tree before its fix. ── */

const rosterStudents = () => {
  const flag = (reason, summary) => ({ reason, summary, evidence: {}, acknowledged: null });
  const row = (id, name, grade, gradeAtRisk, flags) => ({
    studentId: id, name, grade, mark: "21/40", delta: -4, weakTopic: null, gradeAtRisk, paperCount: 12, lastActiveAt: "2026-11-12T08:00:00Z", flags,
  });
  return [
    row("s-1", "Amina Said", "C", false, []),
    row("s-2", "Muhammad Abdelrahman El-Sayed", "E", true, [flag("declining_trend", "Marks fell over the last three papers"), flag("below_target", "Below target")]),
    row("s-3", "Layla Hassan", "D", true, [flag("inactive", "No papers in 30 days")]),
  ];
};
const rosterApp = {
  surface: "teacher-overview",
  state: "populated",
  path: "/teacher/classes/class-1",
  mocks: async (page) => {
    await teacherShellMocks(page);
    await page.route(/\/api\/classes\/class-1(\?|$)/, (route) =>
      jsonRoute(route, { ...CLASS_DETAIL, students: rosterStudents() }),
    );
  },
};

NATIVE_CHECKS.push(
  // 3 + 9. The roster list row carries the signal it exists for, readable in full; the chevron is iOS only and not hand-placed.
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-roster-row-shows-flags-in-full`,
    platform,
    width: 390,
    app: rosterApp,
    async run(page) {
      const rows = page.locator(".lm-native-main a.lm-native-row");
      await rows.first().waitFor();
      const info = await rows.evaluateAll((els) =>
        els.map((el) => {
          const chips = [...el.querySelectorAll("[data-flag-reason]")];
          const low = el.querySelector("[data-grade-at-risk]");
          const more = el.querySelector("[data-flag-more]");
          const clipped = (n) => !!n && (n.scrollHeight > n.clientHeight + 1 || n.scrollWidth > n.clientWidth + 1);
          const box = el.getBoundingClientRect();
          const inside = (n) => !!n && n.getBoundingClientRect().right <= box.right + 0.5 && n.getBoundingClientRect().left >= box.left - 0.5;
          const text = el.querySelector("a > span:nth-of-type(2)");
          const sub = el.querySelector("a > span:nth-of-type(2) > span:nth-of-type(2)") ?? el.querySelector("span.line-clamp-2");
          const chevrons = [...el.querySelectorAll("svg[data-disclosure]")].filter((s) => getComputedStyle(s).display !== "none");
          return {
            name: el.querySelector("[class*=text-body-md]")?.textContent ?? "",
            reason: chips[0]?.textContent ?? null,
            reasonInside: inside(chips[0]),
            more: more?.textContent ?? null,
            low: !!low,
            lowInside: inside(low),
            subClipped: clipped(sub),
            textClipped: clipped(text),
            chevrons: chevrons.length,
            svgs: el.querySelectorAll("svg").length,
          };
        }),
      );
      const by = (n) => info.find((r) => r.name.startsWith(n));
      const [amina, muhammad, layla] = [by("Amina"), by("Muhammad"), by("Layla")];
      if (!amina || !muhammad || !layla) throw new Error(`rows not found by name: ${info.map((r) => r.name)}`);
      if (amina.reason !== null) throw new Error("an unflagged student shows a reason chip");
      if (muhammad.reason !== "Declining trend") throw new Error(`first flag's reason missing: ${muhammad.reason}`);
      if (muhammad.more !== "+1") throw new Error(`"+n" for the remaining flags missing: ${muhammad.more}`);
      if (layla.reason !== "Inactive" || layla.more !== null) throw new Error(`single flag row wrong: ${JSON.stringify(layla)}`);
      if (!muhammad.low || !layla.low || amina.low) throw new Error("the gradeAtRisk marker is not shown by exactly the at-risk grades");
      for (const r of info) {
        if (r.subClipped || r.textClipped) throw new Error(`row text is clipped at 390px: ${JSON.stringify(r)}`);
        if (r.reason && !r.reasonInside) throw new Error("the reason chip overflows the row");
        if (r.low && !r.lowInside) throw new Error("the low-grade marker overflows the row");
      }
      // Item 9: the disclosure chevron is the ListRow's, on iOS only, and the roster places none by hand.
      for (const r of info) {
        if (r.chevrons !== (platform === "ios" ? 1 : 0)) throw new Error(`${platform} row shows ${r.chevrons} disclosure chevrons`);
        if (r.svgs > 1) throw new Error(`row holds ${r.svgs} icons, a second chevron was placed by hand`);
      }
      if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
    },
  })),
);

const reviewItems = [
  ["Muhammad Abdelrahman El-Sayed Hassan", "31", 0.95, "low_confidence"],
  ["Omar Nabil", "4b", 0.52, "low_confidence"],
  ["Amina Said", "12", 0.71, "plagiarism_flag"],
].map(([name, q, conf, reason], i) => ({
  itemId: `item-${i + 1}`, source: "attempt", attemptId: `attempt-${i + 1}`, paperId: null, questionResultId: `qr-${i + 1}`,
  studentId: `student-${i + 1}`, studentDisplayName: name, classId: "class-1", className: "Year 11 Physics", subjectCode: "0625",
  paperNumber: 2, paperVariant: 1, sessionMonth: "May", sessionYear: 2026, questionId: q, reason, status: "open",
  createdAt: "2026-11-12T08:00:00Z", waitingHours: 30, aiAwardedMarks: 2, maximumMarks: 3, confidenceScore: conf,
}));
const reviewApp = (query = "", nextCursor = null) => ({
  surface: "teacher-overview",
  state: "populated",
  path: `/teacher/review${query}`,
  mocks: async (page) => {
    await teacherShellMocks(page);
    await page.route("**/api/teacher/classes", (route) => jsonRoute(route, { classes: CLASS_ROWS }));
    await page.route("**/api/teacher/review?**", (route) =>
      jsonRoute(route, { items: reviewItems, total: reviewItems.length, nextCursor }),
    );
  },
});

NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) => [
    // 4 + 13. The review screen on a phone: filters collapsed, no eyebrow or kicker, first row above the fold.
    {
      id: `native-${platform}-review-first-row-above-fold`,
      platform,
      width: 390,
      app: reviewApp(),
      async run(page) {
        const row = page.locator(".lm-native-main a.lm-native-row").first();
        await row.waitFor();
        const m = await page.evaluate(() => {
          const r = document.querySelector(".lm-native-main a.lm-native-row").getBoundingClientRect();
          const bar = document.querySelector("[data-native-tabbar], nav[aria-label='Primary'], .lm-native-tabbar");
          const visible = (el) => el.checkVisibility() && el.getBoundingClientRect().height > 1;
          return {
            bottom: r.bottom,
            barTop: bar ? bar.getBoundingClientRect().top : innerHeight,
            selects: [...document.querySelectorAll(".lm-native-main select")].filter(visible).length,
            eyebrow: [...document.querySelectorAll(".lm-native-main *")].some((e) => e.textContent === "The teacher's core recurring task" && visible(e)),
            kicker: [...document.querySelectorAll(".lm-native-main p")].some((e) => /Low-confidence marks and integrity flags land here/.test(e.textContent) && visible(e)),
            groupLabel: [...document.querySelectorAll(".lm-native-group-label")].some((e) => /Review queue/.test(e.textContent)),
            filter: !!document.querySelector("[data-review-filter]"),
          };
        });
        if (m.bottom > m.barTop) throw new Error(`the first row ends at ${m.bottom}px, below the fold (tab bar at ${m.barTop}px)`);
        if (m.selects !== 0) throw new Error(`${m.selects} Selects still render in the page, expected one Filter control`);
        if (!m.filter) throw new Error("no Filter control");
        if (m.eyebrow) throw new Error("the eyebrow shows on native");
        if (m.kicker) throw new Error("the kicker shows on native");
        if (m.groupLabel) throw new Error("the list group repeats the heading as a label");
        if ((await page.locator("[data-filter-count]").count()) !== 0) throw new Error("a count badge shows with no filter applied");
        // Filter and View table share one row, and no blank band sits above them.
        const rowInfo = await page.evaluate(() => {
          const f = document.querySelector("[data-review-filter]").getBoundingClientRect();
          const v = [...document.querySelectorAll(".lm-native-main button")].find((b) => b.textContent.trim() === "View table").getBoundingClientRect();
          const row = document.querySelector("[data-review-filter]").parentElement;
          const root = row.parentElement;
          const top = root.getBoundingClientRect().top;
          // The lowest bottom edge of anything rendered above the row, in the page's own content.
          const above = [...document.querySelectorAll(".lm-native-main *")].filter((e) => e.getBoundingClientRect().height > 2 && e.getBoundingClientRect().bottom <= top + 0.5 && !e.contains(root) && e.checkVisibility());
          const prevBottom = above.length ? Math.max(...above.map((e) => e.getBoundingClientRect().bottom)) : document.querySelector(".lm-native-main").getBoundingClientRect().top;
          return { dy: Math.abs(f.top + f.height / 2 - (v.top + v.height / 2)), gap: top - prevBottom };
        });
        if (rowInfo.dy > 4) throw new Error(`Filter and View table are on different rows (${rowInfo.dy}px apart)`);
        if (rowInfo.gap > 20) throw new Error(`a ${rowInfo.gap}px band sits above the Filter row`);
      },
    },
    {
      id: `native-${platform}-review-filter-sheet`,
      platform,
      width: 390,
      app: reviewApp("?class_id=class-1&reason=low_confidence"),
      async run(page) {
        const filter = page.locator("[data-review-filter]");
        await filter.waitFor();
        const badge = (await page.locator("[data-filter-count]").textContent())?.trim();
        if (badge !== "2") throw new Error(`active-count badge is "${badge}", expected 2`);
        await filter.click();
        const dialog = page.getByRole("dialog", { name: "Filter the review queue" });
        await dialog.waitFor();
        await page.waitForTimeout(500);
        for (const label of ["Class", "Reason", "Waiting at least"]) {
          if ((await dialog.getByLabel(label).count()) !== 1) throw new Error(`the sheet lacks the ${label} picker`);
        }
        // The touch floor: 48dp on Android, 44pt on iOS, for every button in the sheet and the Filter button.
        const floor = platform === "android" ? 48 : 44;
        const small = await page.evaluate((fl) => [...document.querySelectorAll("[role=dialog] button, [data-review-filter]")].filter((b) => b.checkVisibility()).map((b) => ({ t: b.textContent.trim() || b.getAttribute("aria-label"), h: b.getBoundingClientRect().height, w: b.getBoundingClientRect().width })).filter((b) => b.h < fl - 0.5 || b.w < fl - 0.5), floor);
        if (small.length) throw new Error(`controls under the ${floor}px floor: ${JSON.stringify(small)}`);
        const pickerGap = await dialog.evaluate((el) => {
          const sel = [...el.querySelectorAll("select")].map((x) => x.closest("label, div").getBoundingClientRect());
          return sel.length > 1 ? sel[1].top - sel[0].bottom : -1;
        });
        if (pickerGap < 10) throw new Error(`the pickers sit ${pickerGap}px apart`);
        // 14. The close X is a pressable chrome control.
        const close = await dialog.getByRole("button", { name: "Close dialog" }).evaluate((el) => ({ press: el.classList.contains("lm-press"), scale: el.classList.contains("lm-press-scale") }));
        if (!close.press || !close.scale) throw new Error(`the close X lacks lm-press / lm-press-scale: ${JSON.stringify(close)}`);
        // 8. The footer is full-width and stacked, primary first, with no top divider.
        const f = await dialog.evaluate((el) => {
          const done = [...el.querySelectorAll("button")].find((b) => b.textContent.trim() === "Done");
          const clear = [...el.querySelectorAll("button")].find((b) => b.textContent.trim() === "Clear filters");
          const foot = done.parentElement;
          const d = done.getBoundingClientRect();
          const c = clear.getBoundingClientRect();
          const s = el.getBoundingClientRect();
          return { doneW: d.width, clearW: c.width, sheetW: s.width, doneTop: d.top, clearTop: c.top, border: getComputedStyle(foot).borderTopWidth };
        });
        if (f.doneW < f.sheetW - 40 || f.clearW < f.sheetW - 40) throw new Error(`footer buttons are not full width: ${JSON.stringify(f)}`);
        if (!(f.doneTop < f.clearTop)) throw new Error(`the primary is not first in the stack: ${JSON.stringify(f)}`);
        if (f.border !== "0px") throw new Error(`the native footer keeps a top divider (${f.border})`);
        if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
        await dialog.getByRole("button", { name: "Done" }).click();
        await dialog.waitFor({ state: "detached" });
      },
    },
    // 5. Review rows lead with the question and keep the name and question whole.
    {
      id: `native-${platform}-review-rows-read-in-full`,
      platform,
      width: 390,
      app: reviewApp(),
      async run(page) {
        const rows = page.locator(".lm-native-main a.lm-native-row");
        await rows.first().waitFor();
        const info = await rows.evaluateAll((els) =>
          els.map((el) => {
            const clipped = (n) => !n || n.scrollHeight > n.clientHeight + 1 || n.scrollWidth > n.clientWidth + 1;
            const title = el.querySelector("a > span:nth-of-type(2) > span:nth-of-type(1)") ?? el.querySelector("span.text-on-surface");
            const q = el.querySelector("[data-review-question]");
            const chip = q?.nextElementSibling;
            const conf = el.querySelector("[data-review-confidence]");
            const trailing = conf?.parentElement;
            return {
              title: title?.textContent ?? "",
              titleClipped: clipped(title),
              question: q?.textContent ?? "",
              questionClipped: clipped(q),
              chip: chip?.textContent ?? "",
              chipBelow: chip && q ? chip.getBoundingClientRect().top >= q.getBoundingClientRect().bottom - 1 : false,
              chipVisible: chip ? chip.getBoundingClientRect().bottom <= el.getBoundingClientRect().bottom + 0.5 : false,
              trailingText: trailing?.textContent ?? "",
              confBg: conf ? getComputedStyle(conf).backgroundColor : null,
              lines: el.getAttribute("data-lines"),
            };
          }),
        );
        const [long, omar, amina] = info;
        if (long.question !== "Q31 · 0625 P2/1 · May 2026") throw new Error(`the subtitle does not lead with the question: "${long.question}"`);
        for (const r of info) {
          if (r.lines !== "3") throw new Error(`row is not a three-line row (data-lines=${r.lines})`);
          if (r.titleClipped) throw new Error(`the name is truncated: "${r.title}"`);
          if (r.questionClipped) throw new Error(`the question line is truncated: "${r.question}"`);
          if (!r.chipBelow || !r.chipVisible) throw new Error(`the reason chip is not whole on its own third line: ${JSON.stringify(r)}`);
          if (!/^\d+%$/.test(r.trailingText)) throw new Error(`the trailing slot holds more than the confidence: "${r.trailingText}"`);
        }
        if (omar.chip !== "Low confidence" || amina.chip !== "Matches mark-scheme wording") throw new Error("the reason chip text is wrong");
        if (long.confBg === omar.confBg) throw new Error("the confidence tone does not follow confidenceTone (95% and 52% look alike)");
        if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
      },
    },
    // 7 + 15. One scroll region and one tab stop in table view; the student cell's 44px sits on its wrapper.
    {
      id: `native-${platform}-table-view-has-one-tab-stop`,
      platform,
      width: 390,
      app: reviewApp(),
      async run(page) {
        await page.getByRole("button", { name: "View table" }).click();
        const region = page.locator(".lm-native-main").getByRole("region").filter({ has: page.locator("table") });
        await region.first().waitFor();
        const m = await page.evaluate(() => {
          const main = document.querySelector(".lm-native-main");
          const regions = [...main.querySelectorAll("[role=region]")];
          const stops = [...main.querySelectorAll("[tabindex='0']")].filter((e) => e.tagName !== "A" && e.tagName !== "BUTTON" && e.tagName !== "INPUT");
          const nested = regions.filter((r) => r.parentElement?.closest("[role=region]")).length;
          const links = [...main.querySelectorAll("tbody tr td:nth-child(2) a")];
          return {
            regions: regions.length,
            stops: stops.length,
            nested,
            links: links.length,
            heights: links.map((a) => a.getBoundingClientRect().height),
            hasClass: links.some((a) => /Year 11 Physics/.test(a.textContent)),
          };
        });
        if (m.regions !== 1) throw new Error(`${m.regions} scroll regions in table view, expected 1`);
        if (m.stops !== 1) throw new Error(`${m.stops} scroll tab stops in table view, expected 1`);
        if (m.nested !== 0) throw new Error("a region nests inside another region");
        // One link to the student carries the name and the class, and every link is at least 44px on a finger.
        if (m.links !== 3) throw new Error(`the student cells hold ${m.links} links, expected one per row`);
        if (m.heights.some((h) => h < 43.5)) throw new Error(`a student-cell link is under 44px: ${m.heights}`);
        if (!m.hasClass) throw new Error("the class is not inside the student link");
        if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
      },
    },
  ]),
);

/** The `Sign out everywhere` confirm: reversible, so not destructive. */
async function openSignOutConfirm(page) {
  const trigger = page.getByRole("button", { name: "Sign out everywhere" }).first();
  await trigger.waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll("button")].some((b) => b.textContent === "Sign out everywhere" && !b.disabled), null, { timeout: 15000 });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Sign out everywhere?" });
  await dialog.waitFor();
  await page.waitForTimeout(500);
  return dialog;
}
/** The Classes table's Delete confirm: destructive. */
async function openDeleteClassConfirm(page) {
  await page.getByRole("button", { name: "View table" }).click();
  await page.getByRole("button", { name: /^Delete/ }).first().click();
  const dialog = page.getByRole("dialog", { name: "Delete this class?" });
  await dialog.waitFor();
  await page.waitForTimeout(500);
  return dialog;
}
const classesApp = {
  surface: "teacher-overview",
  state: "populated",
  path: "/teacher/classes",
  mocks: async (page) => {
    await teacherShellMocks(page);
    await page.route(/\/api\/teacher\/classes(\?|$)/, (route) => jsonRoute(route, { classes: CLASS_ROWS }));
  },
};
const signOutApp = { ...NATIVE_HOME, path: "/student/settings/devices" };
const colourOf = (loc) => loc.evaluate((el) => ({ color: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor }));
const transparent = (bg) => bg === "rgba(0, 0, 0, 0)" || bg === "transparent";

NATIVE_CHECKS.push(
  // 1 + 10. iOS: the confirm row is error only when destructive; the rows press.
  {
    id: "native-ios-confirm-colour-follows-destructive",
    platform: "ios",
    width: 390,
    app: signOutApp,
    async run(page) {
      const dialog = await openSignOutConfirm(page);
      const confirm = await colourOf(dialog.getByRole("button", { name: "Sign out everywhere" }));
      const primary = await tokenColour(page, "--md-primary");
      const error = await tokenColour(page, "--md-error");
      if (confirm.color === error) throw new Error("a reversible confirm is drawn in the error colour");
      if (confirm.color !== primary) throw new Error(`reversible confirm is ${confirm.color}, expected the primary ${primary}`);
      if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
    },
  },
  {
    id: "native-ios-confirm-destructive-is-error-and-rows-press",
    platform: "ios",
    width: 390,
    app: classesApp,
    async run(page) {
      const dialog = await openDeleteClassConfirm(page);
      const confirm = dialog.getByRole("button", { name: "Delete class" });
      if ((await colourOf(confirm)).color !== (await tokenColour(page, "--md-error"))) throw new Error("a destructive confirm is not in the error colour");
      for (const row of await dialog.locator(".lm-action-sheet-row").all()) {
        if (!(await row.evaluate((el) => el.classList.contains("lm-press")))) throw new Error("an action-sheet row lacks lm-press");
      }
      if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
    },
  },
  // 11. A scrim tap is Cancel on the iOS action sheet, and never confirms.
  {
    id: "native-ios-action-sheet-scrim-tap-cancels",
    platform: "ios",
    width: 390,
    app: classesApp,
    async run(page) {
      let deletes = 0;
      page.on("request", (r) => {
        if (r.method() === "DELETE") deletes++;
      });
      const dialog = await openDeleteClassConfirm(page);
      await page.mouse.click(195, 60);
      await dialog.waitFor({ state: "detached", timeout: 3000 }).catch(() => {
        throw new Error("a scrim tap did not cancel the action sheet");
      });
      if (deletes !== 0) throw new Error("a scrim tap confirmed the deletion");
    },
  },
  // 11b. ...and not while the action is pending: the sheet stays up to show its outcome.
  {
    id: "native-ios-action-sheet-scrim-tap-ignored-while-pending",
    platform: "ios",
    width: 390,
    app: classesApp,
    async run(page) {
      await page.route(/\/api\/.*classes\/class-/, (route) => {
        if (route.request().method() === "DELETE") return; // held: the mutation stays pending
        return route.fallback();
      });
      const dialog = await openDeleteClassConfirm(page);
      await dialog.getByRole("button", { name: "Delete class" }).click();
      await page.waitForFunction(() => document.querySelector(".lm-action-sheet [aria-busy=true]"), null, { timeout: 5000 }).catch(() => {
        throw new Error("the confirm never went pending");
      });
      await page.mouse.click(195, 60);
      await page.waitForTimeout(500);
      if (!(await dialog.isVisible()) || (await dialog.evaluate((el) => el.hasAttribute("data-closing")))) throw new Error("a scrim tap closed the sheet while the action was pending");
    },
  },
  // 1 + 2 + 12. Android: M3 dialog actions, error only when destructive, 24px above the title.
  ...[
    ["destructive", classesApp, openDeleteClassConfirm, "Delete class", true],
    ["nondestructive", signOutApp, openSignOutConfirm, "Sign out everywhere", false],
  ].map(([kind, app, open, confirmName, destructive]) => ({
    id: `native-android-confirm-${kind}-follows-m3-actions`,
    platform: "android",
    width: 390,
    app,
    async run(page) {
      const dialog = await open(page);
      const buttons = dialog.getByRole("button");
      if ((await buttons.count()) !== 2) throw new Error(`the confirm has ${await buttons.count()} buttons, expected two text buttons`);
      const cancel = buttons.first();
      const confirm = dialog.getByRole("button", { name: confirmName });
      const [c, k] = [await colourOf(cancel), await colourOf(confirm)];
      if (!transparent(c.bg) || !transparent(k.bg)) throw new Error(`the actions are filled, not text buttons: ${JSON.stringify({ c, k })}`);
      const error = await tokenColour(page, "--md-error");
      const primary = await tokenColour(page, "--md-primary");
      if (destructive && k.color !== error) throw new Error(`destructive confirm is ${k.color}, expected the error role ${error}`);
      if (!destructive && k.color !== primary) throw new Error(`reversible confirm is ${k.color}, expected the primary role ${primary}`);
      if (c.color === error) throw new Error("Cancel is drawn in the error role");
      const [cb, kb] = [await cancel.boundingBox(), await confirm.boundingBox()];
      if (!(kb.x > cb.x)) throw new Error("the confirm does not trail Cancel");
      for (const [name, b] of [["Cancel", cb], [confirmName, kb]]) {
        if (b.height < 47.5 || b.width < 47.5) throw new Error(`${name} is ${b.width}x${b.height}, under the 48dp Android floor`);
      }
      const focus = await page.evaluate(() => document.activeElement?.textContent?.trim());
      if (focus === confirmName) throw new Error("focus landed on the confirm, not Cancel");
      const gap = await dialog.evaluate((el) => el.querySelector("h2").getBoundingClientRect().top - el.getBoundingClientRect().top);
      if (gap < 24) throw new Error(`the title sits ${gap}px below the sheet's top edge, expected at least 24`);
      if (process.env.NF_SHOT_PATH) await page.screenshot({ path: process.env.NF_SHOT_PATH, animations: "disabled" });
    },
  })),
);

/* 6. A bottom tab destination is a root: large title, no back button, however long its trail. */
NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) =>
    [
      ...STUDENT_TAB_PATHS.map((path) => ({ ...NATIVE_HOME, path })),
      ...TEACHER_TAB_PATHS.map((path) => ({ ...NATIVE_TEACHER_HOME, path })),
    ].map((app) => ({
      id: `native-${platform}-tab-root-is-root-${app.path}`,
      platform,
      width: 390,
      app,
      async run(page) {
        const header = page.locator("header[data-title-level]");
        await header.waitFor();
        const level = await header.getAttribute("data-title-level");
        if (level !== "root") throw new Error(`${app.path} is a ${level} page, expected a root`);
        if (!(await page.locator("[data-shell-large-title]").isVisible())) throw new Error(`${app.path} shows no large title`);
        const backs = await page
          .getByRole("button", { name: /back/i })
          .or(page.getByRole("link", { name: /back/i }))
          .filter({ visible: true })
          .count();
        if (backs !== 0) throw new Error(`${app.path} shows ${backs} back control(s)`);
      },
    })),
  ),
);

/* 9. The Create FAB on the Android Grading, Review and Classes tabs never covers the end of the list. */
NATIVE_CHECKS.push({
  id: "native-android-fab-clears-load-more",
  platform: "android",
  width: 390,
  app: reviewApp("", "cursor-2"),
  async run(page) {
    const more = page.getByRole("button", { name: "Load more" });
    await more.waitFor();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(400);
    const r = await page.evaluate(() => {
      const fab = document.querySelector(".lm-native-fab");
      const m = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Load more").getBoundingClientRect();
      const f = fab?.getBoundingClientRect();
      return { fab: !!fab, overlap: f ? !(m.bottom <= f.top || m.top >= f.bottom || m.right <= f.left || m.left >= f.right) : false, mBottom: m.bottom, fTop: f?.top };
    });
    if (!r.fab) throw new Error("no Create FAB on the Review tab");
    if (r.overlap) throw new Error(`the FAB covers Load more (button ends ${r.mBottom}, FAB starts ${r.fTop})`);
  },
});

// Task 12b: the previous page is parked inert under the column during a swipe-back.
const LAYER_PROBE = () => {
  const root = document.documentElement
  const frame = () => {
    const c = document.querySelector("[data-shell-column]")
    const layer = document.querySelector("[data-swipe-layer]")
    const kid = layer?.querySelector("[data-swipe-scroller] > *")
    return {
      left: c ? c.getBoundingClientRect().left : null,
      state: layer?.getAttribute("data-state") ?? null,
      hasPage: Boolean(kid),
      layerX: layer ? layer.getBoundingClientRect().left : null,
      progress: parseFloat(getComputedStyle(root).getPropertyValue("--lm-swipe-progress")) || 0,
      swiping: root.hasAttribute("data-swiping"),
    }
  }
  const probe = { frames: [] }
  window.__layerProbe = probe
  const run = () => {
    const start = performance.now()
    const tick = () => {
      probe.frames.push(frame())
      if (performance.now() - start < 1100) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }
  window.addEventListener("pointerup", run)
  window.__layerFrame = frame
}
async function pushThenEdgeDrag(page, to = 210, hold = 150) {
  await page.getByRole("link", { name: "Classes" }).first().click()
  await page.waitForURL(/\/student\/classes/)
  await page.evaluate(LAYER_PROBE)
  await page.mouse.move(4, 400)
  await page.mouse.down()
  await page.mouse.move(to, 402, { steps: 8 })
  await page.waitForTimeout(hold)
}
NATIVE_CHECKS.push(
  {
    id: "native-ios-swipe-underlay-shows-previous-page-mid-drag",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      const homeText = await page.locator("main").first().innerText()
      await pushThenEdgeDrag(page, 150, 50)
      const got = await page.evaluate(() => {
        const layer = document.querySelector("[data-swipe-layer]")
        const clone = layer?.querySelector("[data-swipe-scroller] > *")
        return {
          frame: window.__layerFrame(),
          hidden: clone?.getAttribute("aria-hidden"),
          inert: clone?.hasAttribute("inert"),
          ids: clone ? clone.querySelectorAll("[id]").length + (clone.id ? 1 : 0) : -1,
          focusable: clone ? clone.querySelectorAll("[tabindex]:not([tabindex='-1']), [autofocus]").length : -1,
          cloneText: clone?.querySelector("main")?.innerText ?? "",
          url: location.pathname,
        }
      })
      await page.mouse.up()
      if (!got.frame.hasPage || got.frame.state !== "on") throw new Error(`no previous page under the column: ${JSON.stringify(got.frame)}`)
      if (got.hidden !== "true" || !got.inert) throw new Error(`the clone is announced or focusable: ${JSON.stringify(got)}`)
      if (got.ids !== 0 || got.focusable !== 0) throw new Error(`the clone kept ids or focusables: ${JSON.stringify(got)}`)
      if (!homeText.trim() || got.cloneText.trim() !== homeText.trim()) throw new Error(`the clone is not the previous (home) page: "${got.cloneText.slice(0, 60)}" vs "${homeText.slice(0, 60)}"`)
      const expected = (got.frame.progress - 1) * 0.3 * 390
      if (!(got.frame.progress > 0.1)) throw new Error(`progress did not move: ${got.frame.progress}`)
      if (Math.abs(got.frame.layerX - expected) > 2) throw new Error(`parallax off the formula: x ${got.frame.layerX}, expected ${expected}`)
    },
  },
  {
    id: "native-ios-swipe-commit-never-shows-empty-ground",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      await pushThenEdgeDrag(page)
      await page.mouse.up()
      await page.waitForURL(/\/student$/)
      await page.waitForTimeout(700)
      const frames = await page.evaluate(() => window.__layerProbe.frames)
      const away = frames.filter((f) => f.left !== null && f.left > 1)
      if (away.length < 3) throw new Error(`only ${away.length} frames with the column away`)
      const bare = away.filter((f) => !f.hasPage)
      if (bare.length) throw new Error(`${bare.length} of ${away.length} frames with the column away had no previous page under it`)
      const last = frames[frames.length - 1]
      if (last.state !== null || last.hasPage) throw new Error(`the underlay outlived the swap: ${JSON.stringify(last)}`)
    },
  },
  {
    id: "native-ios-swipe-cancel-removes-underlay",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
    async run(page) {
      await pushThenEdgeDrag(page, 90, 400)
      const during = await page.evaluate(() => window.__layerFrame())
      await page.mouse.up()
      await page.waitForTimeout(700)
      const after = await page.evaluate(() => ({ f: window.__layerFrame(), html: document.documentElement.hasAttribute("data-swipe-underlay"), kids: document.querySelector("[data-swipe-layer]").childElementCount }))
      if (!/\/student\/classes/.test(page.url())) throw new Error("a short slow swipe navigated")
      if (!during.hasPage) throw new Error("no underlay during the drag")
      if (after.f.state !== null || after.kids !== 0 || after.html) throw new Error(`the clone stayed after a cancel: ${JSON.stringify(after)}`)
    },
  },
  {
    id: "native-ios-swipe-underlay-reduced-motion-has-no-parallax",
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await pushThenEdgeDrag(page, 150, 50)
      const got = await page.evaluate(() => ({ f: window.__layerFrame(), t: getComputedStyle(document.querySelector("[data-swipe-layer]")).translate }))
      await page.mouse.up()
      if (!got.f.hasPage) throw new Error("no underlay under reduced motion")
      if (got.f.layerX !== 0 || (got.t !== "none" && got.t !== "0px")) throw new Error(`parallax ran under reduced motion: x ${got.f.layerX}, translate ${got.t}`)
    },
  },
  ...[
    ["tablet", { platform: "ios", width: 800 }],
    ["other", { width: 390 }],
  ].map(([name, extra]) => ({
    id: `native-${name === "other" ? "other" : "ios"}-swipe-underlay-no-clone-${name}`,
    ...extra,
    app: { ...NATIVE_HOME, path: "/student", init: STANDALONE },
    async run(page) {
      await pushThenEdgeDrag(page, 150, 50)
      const got = await page.evaluate(() => ({ f: window.__layerFrame(), kids: document.querySelector("[data-swipe-layer]").childElementCount, display: getComputedStyle(document.querySelector("[data-swipe-layer]")).display }))
      await page.mouse.up()
      if (got.f.hasPage || got.kids !== 0 || got.display !== "none") throw new Error(`a clone exists off the native frame: ${JSON.stringify(got)}`)
    },
  })),
);

// Task 12b fix round 1: a push through navigate() (a button, not a Link) clones the page as it is
// at that moment, scroll included, so the underlay matches the offset the page is restored to.
// The router is found through React's fiber tree (RouterProvider's `router` prop): the page code
// that calls navigate() all goes through that one function.
NATIVE_CHECKS.push({
  id: "native-ios-swipe-underlay-matches-scroll-after-programmatic-navigate",
  platform: "ios",
  width: 390,
  app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
  async run(page) {
    await page.locator("main").waitFor()
    // Scroll after the page has settled, well past any settle-time capture.
    await page.waitForTimeout(900)
    await page.evaluate(() => window.scrollTo(0, 150))
    await page.waitForTimeout(300)
    const left = await page.evaluate(() => window.scrollY)
    if (!(left > 50)) throw new Error(`the overview did not scroll (scrollY ${left})`)
    await page.evaluate(() => {
      const root = document.getElementById("root")
      const key = Object.keys(root).find((k) => k.startsWith("__reactContainer"))
      const seen = new Set()
      const stack = [root[key]]
      while (stack.length) {
        const fiber = stack.pop()
        if (!fiber || seen.has(fiber)) continue
        seen.add(fiber)
        const router = fiber.memoizedProps?.router
        if (router && typeof router.navigate === "function") return void router.navigate("/student/classes")
        stack.push(fiber.sibling, fiber.child)
      }
      throw new Error("no router in the fiber tree")
    })
    await page.waitForURL(/\/student\/classes/)
    await page.waitForTimeout(500)
    await page.mouse.move(4, 400)
    await page.mouse.down()
    await page.mouse.move(150, 402, { steps: 8 })
    await page.waitForTimeout(50)
    const during = await page.evaluate(() => document.querySelector("[data-swipe-scroller]")?.scrollTop ?? null)
    await page.mouse.up()
    await page.waitForURL(/\/student$/)
    await page.waitForTimeout(500)
    const restored = await page.evaluate(() => window.scrollY)
    if (during === null) throw new Error("no underlay under the column")
    if (Math.abs(during - left) > 2) throw new Error(`the underlay shows the page at scroll ${during}, left at ${left} (restored to ${restored})`)
  },
});

// Task 12b fix round 1: the clone does not restyle per drag frame, and does not repeat the bar actions.
NATIVE_CHECKS.push({
  id: "native-ios-swipe-underlay-is-insulated-and-has-no-duplicate-actions",
  platform: "ios",
  width: 390,
  app: { ...NATIVE_HOME, path: "/student", init: STANDALONE, motion: true },
  async run(page) {
    await pushThenEdgeDrag(page, 150, 50)
    const got = await page.evaluate(() => {
      const scroller = document.querySelector("[data-swipe-scroller]")
      const inner = scroller?.querySelector("main *")
      const trailing = [...(scroller?.querySelectorAll("header [data-shell-title] ~ *") ?? [])]
      return {
        root: getComputedStyle(document.documentElement).getPropertyValue("--lm-swipe-progress"),
        inner: inner ? getComputedStyle(inner).getPropertyValue("--lm-swipe-progress") : null,
        trailing: trailing.length,
        visible: trailing.filter((el) => getComputedStyle(el).visibility !== "hidden").length,
      }
    })
    await page.mouse.up()
    if (!(parseFloat(got.root) > 0.05)) throw new Error(`no drag progress on the root: ${JSON.stringify(got)}`)
    if (got.inner === null || parseFloat(got.inner) !== 0) throw new Error(`the clone inherits the drag progress and restyles each frame: ${JSON.stringify(got)}`)
    if (got.trailing === 0 || got.visible !== 0) throw new Error(`the clone repeats the bar actions: ${JSON.stringify(got)}`)
  },
});

// ---------------------------------------------------------------------------------------------
// Nav coverage: every phone drill-down pushes (src/lib/nav/nativePushDefault.ts).
// The checks assert only that a view transition STARTED and which way it read (`html[data-direction]`
// once the update callback has run), so they hold before and after the motion CSS lands.
// ---------------------------------------------------------------------------------------------

/** Installed standalone (as STANDALONE) and records every document.startViewTransition call. */
const VT_PROBE = () => {
  Object.defineProperty(navigator, "standalone", { value: true })
  const real = window.matchMedia.bind(window)
  window.matchMedia = (q) =>
    q.includes("display-mode: standalone")
      ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} }
      : real(q)
  // The harness's fixed clock fakes performance.now/measure on the instance; keep the real ones.
  window.__realPerf = {}
  for (const k of ["now", "measure", "getEntriesByName", "clearMeasures"]) window.__realPerf[k] = performance[k].bind(performance)
  window.__vt = []
  const start = document.startViewTransition?.bind(document)
  if (start) {
    document.startViewTransition = (arg) => {
      const rec = { from: location.pathname, to: null, direction: null }
      window.__vt.push(rec)
      const transition = start(arg)
      transition.updateCallbackDone
        .then(() => {
          rec.to = location.pathname
          rec.direction = document.documentElement.dataset.direction
        })
        .catch(() => {})
      return transition
    }
  }
}

const PUSH_SUBJECT_MOCKS = async (page) => {
  await NATIVE_SUBJECT.mocks(page)
  // Overview lists the subjects; the subject page lists a paper so its history row can be tapped.
  await page.route(/\/api\/student\/subject\/0606(\?|$)/, (route) =>
    jsonRoute(route, {
      ...SUBJECT_DETAIL,
      paperHistory: [{ id: "paper-1", paper: "0606/12 · Oct 2025", note: "Attempt 1", marks: "52/80", pct: "65%", grade: "B", gradeColor: "primary", tab: "history" }],
    }),
  )
}
const PUSH_APP = (path) => ({ ...NATIVE_HOME, path, init: VT_PROBE, mocks: PUSH_SUBJECT_MOCKS })

const vtLog = (page) => page.evaluate(() => window.__vt)
async function expectOneTransition(page, to, direction) {
  await page.waitForFunction(() => window.__vt.some((r) => r.direction !== null), null, { timeout: 5000 }).catch(() => {})
  const log = await vtLog(page)
  if (log.length !== 1) throw new Error(`expected one view transition, saw ${log.length}: ${JSON.stringify(log)}`)
  if (log[0].direction !== direction) throw new Error(`direction ${log[0].direction}, expected ${direction}`)
  if (to && log[0].to !== to) throw new Error(`transition went to ${log[0].to}, expected ${to}`)
}
async function expectNoTransition(page, what) {
  await page.waitForTimeout(700)
  const log = await vtLog(page)
  if (log.length) throw new Error(`${what} started a view transition: ${JSON.stringify(log)}`)
}
const routerNavigate = (page, to, options) =>
  page.evaluate(([t, o]) => {
    if (!window.__lemelyRouter) throw new Error("no window.__lemelyRouter (harness flag missing)")
    return window.__lemelyRouter.navigate(t, o)
  }, [to, options])

const PUSH_CASES = {
  link: {
    path: "/student",
    to: "/student/subject/0606",
    async act(page) {
      await page.locator('main a[href="/student/subject/0606"]').first().click()
    },
  },
  programmatic: {
    path: "/student/subject/0606",
    to: "/student/result/paper-1",
    async act(page) {
      await page.getByRole("button", { name: /0606\/12/ }).first().evaluate((el) => el.click())
    },
  },
  notification: {
    path: "/student/notifications",
    to: "/student/announcements",
    async act(page) {
      await page.getByRole("button", { name: "Open" }).first().evaluate((el) => el.click())
    },
  },
}

NATIVE_CHECKS.push(
  ...["ios", "android"].flatMap((platform) =>
    Object.entries(PUSH_CASES).map(([name, c]) => ({
      id: `native-${platform}-push-default-${name}-starts-a-forward-transition`,
      platform,
      width: 390,
      app: PUSH_APP(c.path),
      async run(page) {
        await page.locator("main").waitFor()
        await c.act(page)
        await page.waitForURL(`**${c.to}`)
        await expectOneTransition(page, c.to, "forward")
      },
    })),
  ),
  ...["ios", "android"].map((platform) => ({
    id: `native-${platform}-push-default-back-plays-back`,
    platform,
    width: 390,
    app: PUSH_APP("/student"),
    async run(page) {
      await page.locator("main").waitFor()
      await PUSH_CASES.link.act(page)
      await page.waitForURL("**/student/subject/0606")
      await expectOneTransition(page, "/student/subject/0606", "forward")
      await page.evaluate(() => window.history.back())
      await page.waitForURL(/\/student$/)
      await page.waitForFunction(() => window.__vt.length >= 2 && window.__vt[1].direction !== null, null, { timeout: 5000 }).catch(() => {})
      const log = await vtLog(page)
      if (log.length !== 2 || log[1].direction !== "back") throw new Error(`back did not play back: ${JSON.stringify(log)}`)
    },
  })),
  // Nothing changes where the native frame is not active.
  ...[
    ["desktop", { width: 1440 }],
    ["other-390", { width: 390 }],
    ["tablet-ios-800", { width: 800, platform: "ios" }],
  ].flatMap(([name, frame]) =>
    Object.entries(PUSH_CASES)
      // On the touch tablet the notification card's Open tap opens its long-press popover instead
      // (pre-existing, unrelated); the same navigate() call is covered by the programmatic case.
      .filter(([caseName]) => !(name.startsWith("tablet") && caseName === "notification"))
      .map(([caseName, c]) => ({
      id: `native-push-default-none-on-${name}-${caseName}`,
      ...frame,
      app: PUSH_APP(c.path),
      async run(page) {
        await page.locator("main").waitFor()
        await c.act(page).catch(async () => {
          // A phone-only row may be absent on a wide layout; the programmatic route is the same call.
          await routerNavigate(page, c.to)
        })
        await page.waitForURL(`**${c.to}`)
        await expectNoTransition(page, `${name} ${caseName}`)
      },
    })),
  ),
  {
    id: "native-ios-push-default-none-for-a-search-param-change",
    platform: "ios",
    width: 390,
    app: PUSH_APP("/student/classes"),
    async run(page) {
      await page.locator("main").waitFor()
      await routerNavigate(page, "?filter=open")
      await page.waitForURL(/filter=open/)
      await expectNoTransition(page, "a search-only navigation")
    },
  },
  {
    id: "native-ios-push-default-none-for-explicit-false",
    platform: "ios",
    width: 390,
    app: PUSH_APP("/student"),
    async run(page) {
      await page.locator("main").waitFor()
      await routerNavigate(page, "/student/classes", { viewTransition: false })
      await page.waitForURL(/\/student\/classes/)
      await expectNoTransition(page, "viewTransition: false")
    },
  },
  {
    id: "native-ios-push-default-router-exposure-pushes",
    platform: "ios",
    width: 390,
    app: PUSH_APP("/student"),
    async run(page) {
      await page.locator("main").waitFor()
      // Control: the window router (harness flag) drives a programmatic push through the middleware.
      await routerNavigate(page, "/student/classes")
      await page.waitForURL(/\/student\/classes/)
      await expectOneTransition(page, "/student/classes", "forward")
    },
  },
  ...[
    ["bell-row", SHEET_NAV_CASES[0]],
    ["bell-footer", SHEET_NAV_CASES[1]],
    ["account-row", SHEET_NAV_CASES[2]],
    [
      "more-row",
      {
        to: "/student/classes",
        async open(page) {
          await page.getByRole("navigation", { name: "Primary" }).getByRole("button", { name: "More" }).click()
          const dialog = page.getByRole("dialog", { name: "More" })
          await dialog.waitFor()
          return { dialog, row: dialog.getByRole("link").first() }
        },
      },
    ],
  ].map(([name, c]) => ({
    id: `native-ios-push-default-none-for-sheet-${name}`,
    platform: "ios",
    width: 390,
    app: { ...NATIVE_HOME, init: VT_PROBE, mocks: PUSH_SUBJECT_MOCKS },
    async run(page) {
      const { row } = await c.open(page)
      await row.click()
      await page.waitForFunction(() => location.pathname !== "/student", null, { timeout: 5000 })
      await expectNoTransition(page, `a ${name} tap`)
    },
  })),
);

// The swipe-back snapshot walk is timed (performance.measure "lemely:snapshot-capture"). The figure
// goes to the log so a report can quote it; the check fails only when nothing was measured.
NATIVE_CHECKS.push({
  id: "native-ios-snapshot-capture-is-measured",
  platform: "ios",
  width: 390,
  app: PUSH_APP("/student"),
  async run(page) {
    await page.locator("main").waitFor()
    // Put the real User Timing methods back (VT_PROBE kept them) so the figure is a real one.
    await page.evaluate(() => Object.assign(performance, window.__realPerf))
    await PUSH_CASES.link.act(page)
    await page.waitForURL("**/student/subject/0606")
    const got = await page.evaluate(() =>
      performance.getEntriesByName("lemely:snapshot-capture").map((e) => ({ ms: e.duration, ...e.detail })),
    )
    if (!got.length) throw new Error("a push left no lemely:snapshot-capture measure")
    console.log(`      capture timing: ${got.map((g) => `${g.ms.toFixed(1)}ms (${g.outcome})`).join(", ")}`)
  },
});
