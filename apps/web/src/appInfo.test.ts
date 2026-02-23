import { expect, test } from "vitest";

import { APP_NAME, APP_TAGLINE } from "./appInfo";

test("app metadata is stable", () => {
  expect(APP_NAME).toBe("Autonoma");
  expect(APP_TAGLINE).toContain("Infrastructure");
});
