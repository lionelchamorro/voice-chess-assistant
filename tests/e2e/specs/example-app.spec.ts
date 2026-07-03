import { expect, test } from "@playwright/test";

test("example app shows transcript and tool-driven board updates", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Voice Chess Coach" })).toBeVisible();
  await page.getByRole("button", { name: "Connect session", exact: true }).click();
  await page.getByRole("button", { name: "Reset", exact: true }).click();

  await expect(page.getByTestId("connection-status")).toHaveText("connected");
  await expect(page.getByTestId("conversation-state")).toHaveText("idle");
  await expect(page.getByTestId("board-turn")).toHaveText(/white to move/i);

  await page.getByLabel("Assistant prompt").fill("Play e2 to e4");
  await page.getByRole("button", { name: "Send prompt", exact: true }).click();

  await expect(page.getByTestId("conversation-state")).toHaveText("speaking");
  await expect(page.getByTestId("conversation-messages")).toContainText("Play e2 to e4");
  await expect(page.getByTestId("conversation-messages")).toContainText("I played e4");
  await expect(page.getByTestId("tool-call-list")).toContainText("make_move");
  await expect(page.getByTestId("board-turn")).toHaveText(/black to move/i);

  await page.getByRole("button", { name: "Highlight e4", exact: true }).click();
  await expect(page.getByTestId("tool-call-list")).toContainText("set_highlight");

  await page.getByRole("button", { name: "Undo the last move", exact: true }).click();
  await expect(page.getByTestId("tool-call-list")).toContainText("undo_move");
  await expect(page.getByTestId("board-turn")).toHaveText(/white to move/i);
});
