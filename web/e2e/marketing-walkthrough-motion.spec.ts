import { expect, test } from "@playwright/test";

test("desktop scroll drives all three pinned walkthrough stages and step navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/landing");
  const how = page.locator("#how");
  const at = async (progress: number) => {
    await page.mouse.wheel(0, 1);
    await how.evaluate(
      (el, p) =>
        window.scrollTo({
          top:
            window.scrollY +
            el.getBoundingClientRect().top +
            (el.getBoundingClientRect().height - innerHeight) * p,
          behavior: "instant",
        }),
      progress,
    );
  };
  await at(0.1);
  await expect(page.getByRole("tab", { name: "01 Upload" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await at(0.5);
  await expect(page.getByRole("tab", { name: "02 Marked" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("tab", { name: "Q3(c)" }).click();
  // Browser focus/layout scroll cannot dismiss the question under interaction.
  await how.evaluate((el) =>
    window.scrollTo({
      top:
        window.scrollY +
        el.getBoundingClientRect().top +
        (el.getBoundingClientRect().height - innerHeight) * 0.8,
      behavior: "instant",
    }),
  );
  await expect(page.getByRole("tab", { name: "02 Marked" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("radio", { name: "Award A1" }).click();
  await expect(page.getByText("Illustration: A1 awarded")).toBeVisible();
  await at(0.85);
  await expect(page.getByRole("tab", { name: "03 Insights" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText("Weak topic found")).toBeVisible();
  await page.getByRole("tab", { name: "01 Upload" }).click();
  await expect(page.getByText("Uploading 3 photos")).toBeVisible();
  await expect
    .poll(async () =>
      how.evaluate(
        (el) =>
          -el.getBoundingClientRect().top /
          (el.getBoundingClientRect().height - innerHeight),
      ),
    )
    .toBeLessThan(0.34);
});

test("mobile keeps the full progressive walkthrough in document flow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/landing");
  const scenes = page.locator("#how [data-walkthrough-step]");
  await expect(scenes).toHaveCount(3);
  const handwriting = page.locator(".brand-photo-stack .brand-hand");
  const fits = await handwriting.evaluate(
    (el) =>
      el.getBoundingClientRect().height <=
      el.parentElement!.getBoundingClientRect().height,
  );
  expect(fits).toBe(true);
  await scenes.nth(2).scrollIntoViewIfNeeded();
  await expect(scenes.nth(2)).toHaveAttribute("data-active", "true");
  await expect(
    page.getByText("ILLUSTRATION · NO REPORT IS SENT"),
  ).toBeVisible();
  await scenes.nth(1).scrollIntoViewIfNeeded();
  await page.getByRole("tab", { name: "Q3(c)" }).click();
  await expect(page.getByText("AI confidence 72%")).toBeVisible();
});

test("reduced motion removes pinned travel and retains keyboard-accessible stages", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/landing");
  const how = page.locator("#how");
  expect(
    await how.evaluate((el) => el.getBoundingClientRect().height),
  ).toBeLessThan(2000);
  await page.getByRole("tab", { name: "01 Upload" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "02 Marked" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("ArrowRight");
  await expect(page.getByText("Weak topic found")).toBeVisible();
});
