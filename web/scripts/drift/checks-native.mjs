import {
  STUDENT_PROFILE,
  studentShellMocks,
  teacherShellMocks,
} from "./mocks.mjs";

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
    app: { ...NATIVE_HOME, path: "/student/practice/0606" },
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
    id: "native-other-has-no-large-title",
    width: 390,
    app: NATIVE_HOME,
    async run(page) {
      if (await page.locator("[data-shell-large-title]").isVisible())
        throw new Error("other platform shows the native large title");
    },
  },
);
