import { NATIVE_PREVIEW } from "./native-preview.mjs"
import { STUDENT_PROFILE, studentShellMocks, teacherShellMocks } from "./mocks.mjs"

/*
 * Native phone frame vs the design A preview (?platform=…&page=…), at 390x844
 * for both platforms (user instruction), light and dark. Gate scenes: 0 px, or
 * at most 15% with an approved justification. The existing student-/teacher-
 * scenes run without a UA ("other") and must not change.
 */
const NO_GUTTER = "html{scrollbar-gutter:auto!important}"
export const DETAIL_PATH = "/student/practice/0606"
/** The app's bar title on DETAIL_PATH (studentPageTitle); confirmed in Step 2. */
const DETAIL_TITLE = "0606"
/** The app's iOS back label on DETAIL_PATH: the parent crumb's label (Task 4
 * NativeBack); confirmed by probe: trail is Practice / 0606. The preview's `.as-back-l` reads "Overview". */
const DETAIL_BACK_LABEL = "Practice"

const app = (extra = {}) => ({
  path: "/student",
  profile: STUDENT_PROFILE,
  mocks: studentShellMocks("populated"),
  css: NO_GUTTER,
  ...extra,
})

async function scrollPast(page) {
  await page.evaluate(() => window.scrollTo(0, 240))
  await page.waitForFunction(() => document.querySelector("header[data-title-level]")?.getAttribute("data-collapsed") === "true")
}
async function previewScroll(page) {
  await page.evaluate(() => window.scrollTo(0, 240))
  await page.waitForSelector(`${NATIVE_PREVIEW.bar}.is-collapsed`)
}
async function openAppSheet(page, name) {
  await page.getByRole("button", { name }).first().click()
  await page.getByRole("dialog").waitFor()
}

function perPlatform(build) {
  return ["ios", "android"].map((platform) => build(platform))
}

export const NATIVE_SCENES = [
  ...perPlatform((platform) => ({
    id: `native-${platform}-root-top`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app(), preview: { state: "populated", page: "root" },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-root-scrolled`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ act: scrollPast }), preview: { state: "populated", page: "root", act: previewScroll },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-detail`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ path: DETAIL_PATH }),
    preview: {
      state: "populated",
      page: "detail",
      // The preview's detail title and back label are fixed; make them read what the app's route says.
      act: (page) => page.evaluate(([title, titleText, backLabel, backText]) => {
        for (const el of document.querySelectorAll(title)) el.textContent = titleText
        for (const el of document.querySelectorAll(backLabel)) el.textContent = backText
      }, [NATIVE_PREVIEW.inlineTitle, DETAIL_TITLE, `${NATIVE_PREVIEW.back} .as-back-l`, DETAIL_BACK_LABEL]),
    },
  })),
  ...perPlatform((platform) => ({
    id: `native-${platform}-bell`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ act: (page) => openAppSheet(page, /^Notifications/) }),
    preview: {
      state: "populated",
      page: "root",
      act: async (page) => {
        await page.click(NATIVE_PREVIEW.bell)
        await page.waitForSelector(`${NATIVE_PREVIEW.root}[data-sheet="fit"]`)
      },
    },
  })),
  ...perPlatform((platform) => ({
    // The preview's settings sheet opens at the medium detent (data-detents="medium large").
    id: `native-${platform}-settings`, kind: "preview-vs-app", capture: "frame", platform, windows: [390],
    app: app({ path: "/student/settings" }),
    preview: {
      state: "populated",
      page: "root",
      act: async (page) => {
        await page.click(NATIVE_PREVIEW.settings)
        await page.waitForSelector(`${NATIVE_PREVIEW.root}[data-sheet="medium"]`)
      },
    },
  })),
  // Teachers share the frame; no teacher preview exists, so log-only captures.
  ...perPlatform((platform) => ({
    id: `native-teacher-${platform}-root-top`, kind: "before-vs-after", capture: "frame", rule: "log", platform,
    windows: [390], baselineless: [390],
    app: { surface: "teacher-overview", state: "populated", mocks: teacherShellMocks },
  })),
  // Brief §2 proof size for Android; log-only (D9).
  {
    id: "native-android-412-root-top", kind: "preview-vs-app", capture: "frame", rule: "log", platform: "android",
    windows: [412], app: app(), preview: { state: "populated", page: "root" },
  },
  {
    id: "native-android-412-root-scrolled", kind: "preview-vs-app", capture: "frame", rule: "log", platform: "android",
    windows: [412], app: app({ act: scrollPast }), preview: { state: "populated", page: "root", act: previewScroll },
  },
]
