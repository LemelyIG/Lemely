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
      if (n !== 4) throw new Error(`teacher root shows ${n} actions, expected 4`);
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
);

/** D11: two heading texts "repeat" when equal after these steps (see Task 5b). */
const normTitle = (s) => s.trim().toLowerCase().replace(/\s+/g, " ").replace(/^(your|my) /, "");

/** The `to` of each student bottom tab (STUDENT_BOTTOM_TABS in portals/student/shell.tsx)
 * minus the raised Correct action, which is immersive and has no tab root of its own. */
export const STUDENT_TAB_PATHS = ["/student", "/student/classes", "/student/profile"];
/** The `to` of each teacher bottom tab (TEACHER_BOTTOM_TABS in portals/teacher/index.tsx). */
export const TEACHER_TAB_PATHS = ["/teacher", "/teacher/grading", "/teacher/review", "/teacher/classes"];

/** Tab roots of both portals plus the detail paths other checks use. Add a route
 * here when a screen's heading changes; skip only routes the mocks cannot serve,
 * with the reason in a comment. */
const HEADING_ROUTES = [
  ...[...STUDENT_TAB_PATHS, DETAIL_PATH, "/student/tutors"].map((path) => ({ ...NATIVE_HOME, path })),
  ...[...TEACHER_TAB_PATHS, TAB_DRILL_PATH].map((path) => ({ ...NATIVE_TEACHER_HOME, path })),
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
