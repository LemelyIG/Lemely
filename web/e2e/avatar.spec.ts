import fs from "node:fs"
import path from "node:path"
import zlib from "node:zlib"
import { expect, test } from "@playwright/test"
import { reportDir } from "./report-dir"
import { injectSession, readSeed } from "./seed"

/*
 * "A picture set in Profile settings is visible afterwards" — the whole
 * `POST /api/me/avatar` -> `GET /api/me/profile` -> `<Avatar>` path, in a real
 * browser.
 *
 * Every assertion here is about a *painted* image (`naturalWidth > 0`), never
 * about a string arriving: the bug this suite exists for (staging's signed
 * URLs failing to sign, `lemely/io/storage_gcs.py::_signing_token`) produced a
 * 200 with `avatarUrl: null` and a silently unchanged avatar, which any
 * response-shape assertion would have called a pass. The E2E stack runs the
 * `local` storage backend, so it cannot reproduce the GCS signing failure
 * itself — `tests/test_storage_gcs.py` pins that half; this pins that the
 * client actually renders whatever URL the server hands it, in both places the
 * product promises a picture: the Profile settings card and the portal sidebar.
 */

/** An 8x8 solid-red PNG, built here so the fixture needs no image library. */
function pngBytes(): Buffer {
  const width = 8
  const height = 8
  const raw = Buffer.alloc((width * 3 + 1) * height)
  for (let y = 0; y < height; y++) {
    const row = y * (width * 3 + 1)
    raw[row] = 0 // filter type: none
    for (let x = 0; x < width; x++) {
      raw[row + 1 + x * 3] = 220
      raw[row + 2 + x * 3] = 40
      raw[row + 3 + x * 3] = 40
    }
  }

  const crcTable: number[] = []
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    crcTable[n] = c >>> 0
  }
  const chunk = (type: string, data: Buffer): Buffer => {
    const length = Buffer.alloc(4)
    length.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type, "ascii"), data])
    let crc = 0xffffffff
    for (const byte of body) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8)
    const checksum = Buffer.alloc(4)
    checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0)
    return Buffer.concat([length, body, checksum])
  }

  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 2 // colour type: truecolour
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ])
}

test("a picture set in Profile settings is visible afterwards", async ({ page }) => {
  const seed = readSeed()
  await injectSession(page, {
    accessToken: seed.teacher.accessToken,
    userId: seed.teacher.userId,
    role: "teacher",
  })

  fs.mkdirSync(reportDir(), { recursive: true })
  const filePath = path.join(reportDir(), "avatar-fixture.png")
  fs.writeFileSync(filePath, pngBytes())

  await page.goto("/settings/profile")
  await expect(page.getByRole("heading", { name: "Profile picture" })).toBeVisible()

  const uploaded = page.waitForResponse(
    (r) => r.url().includes("/api/me/avatar") && r.request().method() === "POST",
  )
  await page.locator('input[type="file"]').setInputFiles(filePath)
  const response = await uploaded
  expect(response.status()).toBe(200)
  const body = (await response.json()) as { avatarUrl: string | null }
  // Null here is the exact shape of the staging bug: the upload succeeded and
  // the server could not sign a URL for what it had just stored.
  expect(body.avatarUrl, "upload succeeded but the profile carries no avatarUrl").not.toBeNull()

  const settingsAvatar = page.locator('section[aria-labelledby="picture-heading"] img')
  await expect(page.getByRole("button", { name: "Remove picture" })).toBeVisible()
  await expect(settingsAvatar).toHaveCount(1)
  expect(
    await settingsAvatar.evaluate((el: HTMLImageElement) => el.naturalWidth),
    "the picture did not paint in Profile settings",
  ).toBeGreaterThan(0)

  // It must survive a reload, which re-reads GET /api/me/profile and signs a
  // fresh URL rather than replaying the upload response.
  await page.reload()
  await expect(page.getByRole("button", { name: "Remove picture" })).toBeVisible()
  await expect(settingsAvatar).toHaveCount(1)
  expect(
    await settingsAvatar.evaluate((el: HTMLImageElement) => el.naturalWidth),
    "the picture did not paint after a reload",
  ).toBeGreaterThan(0)

  // "Shown next to your name in the sidebar", per the screen's own copy.
  await page.goto("/teacher")
  await expect(page.getByText(seed.teacher.displayName).first()).toBeVisible()
  const portalAvatars = page.locator('div[role="img"] img')
  const painted = await portalAvatars.evaluateAll((els) =>
    (els as HTMLImageElement[]).map((el) => el.naturalWidth),
  )
  expect(painted.length, "the portal rendered no avatar image at all").toBeGreaterThan(0)
  for (const width of painted) {
    expect(width, "an avatar in the portal did not paint").toBeGreaterThan(0)
  }
})
