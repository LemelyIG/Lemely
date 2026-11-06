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
  await page.getByRole("button", { name: "Explain Q3(c)" }).click();
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
  await expect(page.getByRole("radio", { name: "Award A1" })).toBeChecked();
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

test("mobile shows How it works as a three-card stack with every step reachable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/landing");
  const deck = page.getByRole("region", { name: "How it works" });
  await expect(deck.getByRole("status")).toHaveText("1 / 3");
  await expect(deck.getByRole("heading", { name: "Upload" })).toBeVisible();
  const cards = deck.getByRole("group", { name: "How it works cards" });
  await cards.press("ArrowRight");
  await expect(deck.getByRole("status")).toHaveText("2 / 3");
  await expect(deck.getByRole("heading", { name: "Marked" })).toBeVisible();
  await cards.press("ArrowRight");
  await expect(deck.getByRole("heading", { name: "Insights" })).toBeVisible();
  await expect(deck.getByText("Units & SI")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
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
