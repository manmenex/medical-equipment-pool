import { describe, expect, it } from "vitest";

import { isBackendSessionId } from "@/utils/legacyImportSessionId";

// Roadmap PR20F design §41 "category dispatch test": this discriminator is
// the entire routing mechanism between the real Equipment Master workflow
// and the PR19B mock skeleton on the shared /imports/:sessionId route --
// every real backend ImportSession id is a UUID path param
// (backend/app/api/v1/import_sessions.py), every mock/fixture id
// (services/legacyImportFixtures.ts) is deliberately not.
describe("isBackendSessionId", () => {
  it("accepts a lowercase UUID", () => {
    expect(isBackendSessionId("11111111-1111-4111-8111-111111111111")).toBe(true);
  });

  it("accepts an uppercase UUID", () => {
    expect(isBackendSessionId("11111111-1111-4111-8111-111111111111".toUpperCase())).toBe(true);
  });

  it.each(["demo-completed", "preview-3", "session-1", "", undefined])(
    "rejects a mock/fixture-shaped id %j",
    (value) => {
      expect(isBackendSessionId(value)).toBe(false);
    }
  );

  it("rejects a UUID-like string with the wrong segment lengths", () => {
    expect(isBackendSessionId("1111111-1111-4111-8111-111111111111")).toBe(false);
  });
});
