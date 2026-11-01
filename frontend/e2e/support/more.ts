import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { PASSWORD, type Persona } from "./helpers";

export { PASSWORD };

export async function auditActorsFor(
  api: APIRequestContext,
  adminToken: string,
  transactionId: string,
): Promise<Array<{ user_id: string | null; action: string }>> {
  const res = await api.get("audit-logs?entity_type=borrow_transaction&limit=200", {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  expect(res.ok()).toBeTruthy();
  const rows = (await res.json()) as Array<{ user_id: string | null; action: string; entity_id: string | null }>;
  return rows.filter((r) => r.entity_id === transactionId);
}

export async function userIdOf(api: APIRequestContext, token: string, who: Persona): Promise<string> {
  const res = await api.get("users?limit=200", { headers: { Authorization: `Bearer ${token}` } });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  const rows = (body.items ?? body) as Array<{ id: string; employee_code: string }>;
  return rows.find((u) => u.employee_code === who.code)!.id;
}

/** Patches one `meta` record (e.g. to age the snapshot for the staleness drill). */
export async function setMeta(page: Page, name: string, value: unknown): Promise<void> {
  await page.evaluate(
    ({ n, v }) =>
      new Promise<void>((resolve, reject) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const tx = open.result.transaction("meta", "readwrite");
          tx.objectStore("meta").put({ name: n, value: v });
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        };
      }),
    { n: name, v: value },
  );
}

// ---------------------------------------------------------------------------
// Review page (/sync-review)
// ---------------------------------------------------------------------------

export function reviewItem(page: Page, text: string) {
  return page.getByTestId("sync-review-item").filter({ hasText: text });
}

export async function dismissReviewItem(page: Page, text: string): Promise<void> {
  await reviewItem(page, text).getByRole("button", { name: "ปิดรายการ" }).click();
  const dialog = page.getByRole("dialog", { name: "ยืนยันการปิดรายการ" });
  await dialog.getByRole("combobox").selectOption("duplicate_physical_entry");
  await dialog.getByRole("button", { name: "ยืนยัน" }).click();
  await expect(page.getByTestId("sync-review-message")).toHaveText("ปิดรายการเรียบร้อยแล้ว");
}

export async function applyReviewItemNow(page: Page, text: string): Promise<void> {
  await reviewItem(page, text).getByRole("button", { name: "บันทึกทันที" }).click();
  const dialog = page.getByRole("dialog", { name: "ยืนยันการบันทึกทันที" });
  await dialog.getByRole("button", { name: "ยืนยัน" }).click();
  await expect(page.getByTestId("sync-review-message")).toHaveText("บันทึกรายการเรียบร้อยแล้ว");
}
