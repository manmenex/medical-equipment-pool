import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import {
  LEGACY_MIGRATION_AUTHORITY_SCOPE,
  approveLegacyMigrationAuthority,
  findLegacyMigrationAuthorityByChecksum,
} from "@/services/legacyMigrationAuthorityClient";

afterEach(() => {
  vi.restoreAllMocks();
});

const CHECKSUM = "a".repeat(64);

// Roadmap PR21E0/PR21E: exact request-shape contract tests for the sole
// Administrator-only production write path for LegacyMigrationAuthority
// (backend/app/api/v1/legacy_migration_authorities.py). Scope is always
// the one hardcoded constant -- never a caller-supplied value.
describe("legacyMigrationAuthorityClient", () => {
  it("approves with exactly the fixed scope and the given checksum, no other field", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      status: 201,
      data: { id: "auth-1", scope: LEGACY_MIGRATION_AUTHORITY_SCOPE, approved_workbook_sha256: CHECKSUM },
    });

    const result = await approveLegacyMigrationAuthority(CHECKSUM);

    expect(postSpy).toHaveBeenCalledWith("/legacy-migration-authorities", {
      scope: LEGACY_MIGRATION_AUTHORITY_SCOPE,
      approved_workbook_sha256: CHECKSUM,
    });
    expect(LEGACY_MIGRATION_AUTHORITY_SCOPE).toBe("pr21_legacy_transaction_history_v1");
    expect(result.created).toBe(true);
  });

  it("reports created=false for an idempotent retry (backend 200), never inferred from response content", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      status: 200,
      data: { id: "auth-1", scope: LEGACY_MIGRATION_AUTHORITY_SCOPE, approved_workbook_sha256: CHECKSUM },
    });

    const result = await approveLegacyMigrationAuthority(CHECKSUM);

    expect(postSpy).toHaveBeenCalledTimes(1);
    expect(result.created).toBe(false);
  });

  it("propagates a scope-conflict failure (409) rather than swallowing it", async () => {
    const conflict = Object.assign(new Error("conflict"), {
      isAxiosError: true,
      response: { status: 409, data: { code: "LEGACY_MIGRATION_AUTHORITY_SCOPE_CONFLICT" } },
    });
    vi.spyOn(api, "post").mockRejectedValue(conflict);

    await expect(approveLegacyMigrationAuthority(CHECKSUM)).rejects.toBe(conflict);
  });

  it("looks up by checksum via a query param, never a path segment", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({
      data: { id: "auth-1", scope: LEGACY_MIGRATION_AUTHORITY_SCOPE, approved_workbook_sha256: CHECKSUM },
    });

    const authority = await findLegacyMigrationAuthorityByChecksum(CHECKSUM);

    expect(getSpy).toHaveBeenCalledWith("/legacy-migration-authorities", { params: { checksum: CHECKSUM } });
    expect(authority?.id).toBe("auth-1");
  });

  it("returns null (never throws) for the specific 'not yet approved' 404 case", async () => {
    const notFound = Object.assign(new Error("not found"), {
      isAxiosError: true,
      response: { status: 404, data: { code: "LEGACY_MIGRATION_AUTHORITY_NOT_FOUND" } },
    });
    vi.spyOn(api, "get").mockRejectedValue(notFound);

    const authority = await findLegacyMigrationAuthorityByChecksum(CHECKSUM);

    expect(authority).toBeNull();
  });

  it("rethrows a non-404 failure (network/500/permission), never silently treating it as 'not approved'", async () => {
    const serverError = Object.assign(new Error("boom"), {
      isAxiosError: true,
      response: { status: 500, data: {} },
    });
    vi.spyOn(api, "get").mockRejectedValue(serverError);

    await expect(findLegacyMigrationAuthorityByChecksum(CHECKSUM)).rejects.toBe(serverError);
  });
});
