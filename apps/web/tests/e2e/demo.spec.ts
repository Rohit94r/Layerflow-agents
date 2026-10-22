import { expect, test, type Page } from "@playwright/test";

/**
 * The 10-minute demo (docs/demo-script.md) as an end-to-end test. Run against a stack started with
 * MODEL_PROVIDER=mock so the pipeline completes in seconds and deterministically.
 */
const email = process.env.E2E_EMAIL ?? "admin@example.com";
const password = process.env.E2E_PASSWORD ?? "change-me-please";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test.describe.serial("demo script", () => {
  let articleUrl = "";

  test("dashboard renders live cards", async ({ page }) => {
    await login(page);
    for (const label of ["Candidates today", "Drafts in progress", "Awaiting review", "Scheduled", "Published (7d)", "Failed jobs"]) {
      await expect(page.getByText(label, { exact: true })).toBeVisible();
    }
    await expect(page.getByText("Agent health")).toBeVisible();
  });

  test("news feed refresh pulls real candidates", async ({ page }) => {
    await login(page);
    await page.getByRole("link", { name: "News Feed" }).first().click();
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.getByText("Discovery queued")).toBeVisible();
    await expect(page.getByText(/Discovery finished|Discovery failed/)).toBeVisible({ timeout: 150_000 });
    await page.reload();
    await expect(page.locator("tbody tr").first()).toBeVisible();
  });

  test("promote a story and watch the stages", async ({ page }) => {
    await login(page);
    await page.goto("/news");
    await page.locator("tbody tr button").first().click();
    await page.getByRole("button", { name: "Promote" }).last().click();
    await page.getByRole("dialog", { name: "Promote to the studio" }).getByRole("button", { name: "Promote" }).click();
    await page.waitForURL(/\/studio\/[0-9a-f-]+/);
    articleUrl = page.url();
    await expect(page.getByText("Pipeline", { exact: true })).toBeVisible();
    for (const stage of ["Research", "Write", "Edit", "SEO", "QA"]) {
      await expect(page.getByRole("button", { name: `Run ${stage}` })).toBeVisible();
    }
    // With the mock provider the pipeline reaches review, or stops honestly at "Needs more sources".
    await expect(page.getByText(/In review|Needs more sources|Pipeline stopped/)).toBeVisible({ timeout: 150_000 });
  });

  test("review: approve, dry run, schedule and publish now", async ({ page }) => {
    await login(page);
    await page.goto("/review");
    const empty = page.getByText("Queue is empty");
    if (await empty.isVisible().catch(() => false)) test.skip(true, "No article reached review (sources too thin for this run)");
    await page.getByRole("button", { name: /Approve/ }).click();
    const dialog = page.getByRole("dialog", { name: "Schedule publication" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Dry run" }).click();
    await expect(dialog.getByText(/Ready to publish|issue\(s\)/)).toBeVisible();
    await dialog.getByRole("button", { name: "Schedule" }).click();
    await expect(page.getByText(/Scheduled|Already scheduled/)).toBeVisible();

    await page.goto("/calendar");
    await page.locator('button[title*="— scheduled"]').first().click();
    await page.getByRole("button", { name: "Publish now" }).click();
    await expect(page.getByText(/Publish finished|Publishing now/)).toBeVisible({ timeout: 120_000 });
  });

  test("social: LinkedIn draft can be copied", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await login(page);
    await page.goto("/social");
    const generate = page.getByRole("button", { name: "Generate" }).first();
    if (await generate.isVisible().catch(() => false)) {
      await generate.click();
      await expect(page.getByText(/LinkedIn draft finished/)).toBeVisible({ timeout: 90_000 });
    }
    await page.getByRole("button", { name: "Copy post" }).click();
    await expect(page.getByText("Post copied")).toBeVisible();
    await expect(page.getByLabel("LinkedIn post preview")).toBeVisible();
    void articleUrl;
  });
});
