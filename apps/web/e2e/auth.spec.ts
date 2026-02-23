import { expect, test } from "@playwright/test";

test("OIDC login link redirects to Keycloak", async ({ page }) => {
  await page.goto("/");
  const loginLink = page.getByRole("link", { name: /log in with oidc/i });
  await expect(loginLink).toHaveAttribute("href", "/v1/auth/login");

  const response = await page.request.get("/v1/auth/login", { maxRedirects: 0 });
  expect(response.status()).toBe(302);
  const location = response.headers()["location"] ?? "";
  expect(location).toMatch(/\/realms\/autonoma\/protocol\/openid-connect\/auth/);
});
