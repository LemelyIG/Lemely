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
);

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
