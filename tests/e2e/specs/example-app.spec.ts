import { expect, test } from "@playwright/test";

test("example app connects and resets the board", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /controlled board demo/i })).toBeVisible();
  await page.getByRole("button", { name: "Connect", exact: true }).click();

  await expect(page.getByTestId("connection-status")).toHaveText("Status: connected");
  await expect(page.getByTestId("board-turn")).toHaveText("Turn: white");

  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.getByTestId("board-turn")).toHaveText("Turn: black");

  await page.getByRole("button", { name: "Reset" }).click();
  await expect(page.getByTestId("board-turn")).toHaveText("Turn: white");
});
