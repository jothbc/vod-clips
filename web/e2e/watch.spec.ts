import { expect, test } from "@playwright/test";

const VIDEO_ID = "untitled_video_-_made_with_clipchamp__3";
const WATCH_URL = `http://localhost:5173/watch/${VIDEO_ID}`;
const API_BASE = "http://localhost:8000";

test.describe("Watch page e2e", () => {
  test.beforeEach(async ({ request }) => {
    const ready = await request.get(`${API_BASE}/api/ready`);
    expect(ready.ok()).toBeTruthy();
  });

  test("API returns video with correct stream URL", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/videos/${VIDEO_ID}`);
    expect(res.ok()).toBeTruthy();
    const data = await res.json();
    expect(data.id).toBe(VIDEO_ID);
    expect(data.title).toContain("Clipchamp");
    expect(data.stream_url).toBe(`/api/v2/media/${VIDEO_ID}/source.mp4`);
    expect(data.kind).toBe("original");
  });

  test("source video is streamable", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/v2/media/${VIDEO_ID}/source.mp4`);
    expect(res.ok()).toBeTruthy();
    const ct = res.headers()["content-type"] ?? "";
    expect(ct).toContain("video");
  });

  test("watch page loads player and title", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-watch-title")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".v2-watch-title")).toContainText("Clipchamp");
    await expect(page.locator(".v2-player-wrap video")).toBeVisible();
  });

  test("action bar shows pipeline buttons", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-actions")).toBeVisible({ timeout: 15000 });
    const metadataBtn = page.getByRole("button", { name: /Obter metadados/i });
    const clipsBtn = page.getByRole("button", { name: /Gerar clips/i });
    await expect(metadataBtn).toBeVisible();
    await expect(clipsBtn).toBeVisible();
    if (await metadataBtn.isEnabled()) {
      await expect(clipsBtn).toBeDisabled();
    } else {
      await expect(clipsBtn).toBeEnabled();
    }
  });

  test("video element receives valid src", async ({ page }) => {
    await page.goto(WATCH_URL);
    const video = page.locator(".v2-player-wrap video");
    await expect(video).toBeVisible({ timeout: 15000 });
    const src = await video.getAttribute("src");
    expect(src).toContain(VIDEO_ID);
    expect(src).toContain("source.mp4");
  });

  test("navigation: logo returns to home", async ({ page }) => {
    await page.goto(WATCH_URL);
    await page.locator(".v2-logo").click();
    await expect(page).toHaveURL(/localhost:5173\/?$/);
    await expect(page.locator(".v2-hero, .v2-section").first()).toBeVisible({ timeout: 10000 });
  });

  test("system dock visible on desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-system-dock")).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".v2-gauge").first()).toBeVisible();
    await expect(page.locator(".v2-health-dot").first()).toBeVisible();
  });

  test("system dock opens from header on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-system-dock")).toBeHidden();
    await page.getByRole("button", { name: /Sistema/i }).click();
    await expect(page.locator(".v2-system-dock--open")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".v2-gauge").first()).toBeVisible();
  });

  test("sidebar shows contextual title on watch page", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-sidebar-title")).toBeVisible({ timeout: 15000 });
    const title = await page.locator(".v2-sidebar-title").textContent();
    expect(title).toMatch(/Clipes deste VOD|VOD original/);
  });
});

test.describe("Generate clips modal", () => {
  test("does not auto-start analysis", async ({ page }) => {
    await page.goto(WATCH_URL);
    await expect(page.locator(".v2-actions")).toBeVisible({ timeout: 15000 });
    const hasTranscript = await page.getByRole("button", { name: /Gerar clips/i }).isEnabled();
    test.skip(!hasTranscript, "Video needs transcript for Gerar clips button");
    await page.getByRole("button", { name: /Gerar clips/i }).click();
    await expect(page.getByRole("button", { name: /Analisar highlights/i })).toBeVisible();
    await expect(page.getByText(/Analisando highlights/i)).not.toBeVisible();
    const counter = page.getByLabel(/Quantidade de highlights/i);
    await expect(counter).toBeVisible();
    await expect(counter).toHaveValue("15");
  });
});
