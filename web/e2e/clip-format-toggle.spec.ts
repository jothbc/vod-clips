import { expect, test } from "@playwright/test";

const CLIP_URL = "http://localhost:5173/watch/2026-06-22_17-11-29::clip_04";
const API_BASE = "http://localhost:8000";

test.describe("Clip format toggle e2e", () => {
  test.beforeEach(async ({ request }) => {
    const ready = await request.get(`${API_BASE}/api/ready`);
    expect(ready.ok()).toBeTruthy();
  });

  test("shows format toggle when clip has multiple formats", async ({ page, request }) => {
    const detail = await request.get(
      `${API_BASE}/api/v2/videos/${encodeURIComponent("2026-06-22_17-11-29::clip_04")}`
    );
    test.skip(!detail.ok(), "Test clip not available");

    await page.goto(CLIP_URL);
    const toggle = page.getByRole("group", { name: /Formato do clipe/i });
    const data = await detail.json();
    if ((data.formats?.length ?? 0) < 2) {
      await expect(toggle).toBeHidden();
      return;
    }

    await expect(toggle).toBeVisible();
    const video = page.locator(".v2-player-wrap video");
    const desktopSrc = await video.getAttribute("src");
    await page.getByRole("button", { name: /Mobile/i }).click();
    await expect(video).not.toHaveAttribute("src", desktopSrc || "");
    await expect(page).toHaveURL(/format=reels/);
  });
});
