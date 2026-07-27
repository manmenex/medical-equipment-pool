import { describe, expect, it } from "vitest";

import {
  canCorrectTransactionWard,
  canDecommissionEquipment,
  canDispatchOrReceiveEquipment,
  canImportInventory,
  canManageEquipmentMasterData,
  canManageUsers,
  canMarkEquipmentDefective,
  canReactivateEquipment,
  roleLabel,
} from "@/hooks/useAuth";
import type { Role, UserProfile } from "@/types";

// Roadmap PR10 (Role Model Consolidation): the frontend capability layer
// mirrors backend/app/api/v1/deps.py's capability groups exactly. This is
// the complete table-driven matrix for all 3 confirmed roles across every
// exported capability function -- not a security boundary (the backend
// remains authoritative), but a regression here would mean the frontend
// silently offers, or silently hides, an action that disagrees with what
// the backend actually allows.

function makeUser(role: Role): UserProfile {
  return { id: "u1", employee_code: "U001", full_name: "Test User", email: "u@test.dev", role, permissions: {} };
}

const ADMIN = makeUser("administrator");
const STAFF = makeUser("equipment_pool_staff");
const READ_ONLY = makeUser("read_only");

describe("capability layer (EQUIPMENT_POOL_OPERATION_ROLES: administrator + equipment_pool_staff)", () => {
  const cases: [string, (u: typeof ADMIN | null | undefined) => boolean][] = [
    ["canCorrectTransactionWard", canCorrectTransactionWard],
    ["canMarkEquipmentDefective", canMarkEquipmentDefective],
    ["canDispatchOrReceiveEquipment", canDispatchOrReceiveEquipment],
  ];

  for (const [name, fn] of cases) {
    it(`${name}: administrator=true, equipment_pool_staff=true, read_only=false`, () => {
      expect(fn(ADMIN)).toBe(true);
      expect(fn(STAFF)).toBe(true);
      expect(fn(READ_ONLY)).toBe(false);
    });

    it(`${name}: null/undefined user is denied`, () => {
      expect(fn(null)).toBe(false);
      expect(fn(undefined)).toBe(false);
    });
  }
});

describe("capability layer (ADMINISTRATOR_ONLY_ROLES: administrator only)", () => {
  const cases: [string, (u: typeof ADMIN | null | undefined) => boolean][] = [
    ["canManageEquipmentMasterData", canManageEquipmentMasterData],
    ["canReactivateEquipment", canReactivateEquipment],
    ["canDecommissionEquipment", canDecommissionEquipment],
    ["canManageUsers", canManageUsers],
    ["canImportInventory", canImportInventory],
  ];

  for (const [name, fn] of cases) {
    it(`${name}: administrator=true, equipment_pool_staff=false, read_only=false`, () => {
      expect(fn(ADMIN)).toBe(true);
      expect(fn(STAFF)).toBe(false);
      expect(fn(READ_ONLY)).toBe(false);
    });

    it(`${name}: null/undefined user is denied`, () => {
      expect(fn(null)).toBe(false);
      expect(fn(undefined)).toBe(false);
    });
  }
});

describe("roleLabel", () => {
  it("returns the Thai display label for each of the 3 confirmed roles", () => {
    expect(roleLabel("administrator")).toBe("ผู้ดูแลระบบ");
    expect(roleLabel("equipment_pool_staff")).toBe("เจ้าหน้าที่ Equipment Pool");
    expect(roleLabel("read_only")).toBe("ผู้ใช้ทั่วไป (ดูอย่างเดียว)");
  });

  it("falls back to the raw value for an unrecognized role string", () => {
    expect(roleLabel("something_unexpected")).toBe("something_unexpected");
  });
});
