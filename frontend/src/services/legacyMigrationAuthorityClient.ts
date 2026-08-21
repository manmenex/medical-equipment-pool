import axios from "axios";

import { api } from "@/services/api";
import type { LegacyMigrationAuthorityOut, LegacyMigrationAuthorityScope } from "@/types/legacyImportApi";

// Roadmap PR21E0/PR21E: thin wrapper over
// backend/app/api/v1/legacy_migration_authorities.py -- the sole,
// Administrator-only production write path for LegacyMigrationAuthority.
// PR21 V1 has exactly one approved scope; this client hardcodes it rather
// than accepting one from a caller, so no ordinary workflow code path can
// ever submit an operator-typed scope string.
export const LEGACY_MIGRATION_AUTHORITY_SCOPE: LegacyMigrationAuthorityScope = "pr21_legacy_transaction_history_v1";

export interface ApproveLegacyMigrationAuthorityResult {
  authority: LegacyMigrationAuthorityOut;
  // true only for a genuine first approval (backend 201); false for an
  // idempotent retry of an already-approved checksum (backend 200) --
  // never inferred from response content, only from the real HTTP status
  // the backend actually returned.
  created: boolean;
}

// §9/§10 of the task: an explicit, Administrator-only governance action --
// never invoked implicitly from validate/dry-run/execute. The checksum
// passed here must always come from a real ImportSourceOut response
// (services/legacyHistoryImportClient.ts's uploadLegacyHistorySource),
// never hand-typed by an operator in the ordinary workflow.
export async function approveLegacyMigrationAuthority(
  approvedWorkbookSha256: string
): Promise<ApproveLegacyMigrationAuthorityResult> {
  const resp = await api.post<LegacyMigrationAuthorityOut>("/legacy-migration-authorities", {
    scope: LEGACY_MIGRATION_AUTHORITY_SCOPE,
    approved_workbook_sha256: approvedWorkbookSha256,
  });
  return { authority: resp.data, created: resp.status === 201 };
}

// §7 of the task: "is this checksum already approved, and what authority
// owns it?" -- returns `null` for the specific, expected "not yet
// approved" case (backend 404 LEGACY_MIGRATION_AUTHORITY_NOT_FOUND) so
// callers can render an explicit approval step; any other failure (network,
// 500, permission) is rethrown for the caller's own error handling, never
// silently treated as "not approved."
export async function findLegacyMigrationAuthorityByChecksum(
  checksum: string
): Promise<LegacyMigrationAuthorityOut | null> {
  try {
    const resp = await api.get<LegacyMigrationAuthorityOut>("/legacy-migration-authorities", {
      params: { checksum },
    });
    return resp.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      return null;
    }
    throw error;
  }
}
