import { expect, request as pwRequest, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

// Synthetic personas created by support/seed_e2e.py.
export const PASSWORD = "Drill@12345";
export const USERS = {
  admin: { code: "E2EADMIN", name: "Drill Reviewer" },
  poolA: { code: "E2EPOOLA", name: "Drill Pool A" },
  poolB: { code: "E2EPOOLB", name: "Drill Pool B" },
  poolC: { code: "E2EPOOLC", name: "Drill Pool C" },
} as const;
export type Persona = (typeof USERS)[keyof typeof USERS];

export const API = "http://127.0.0.1:8000/api/v1";
export const WARD_1 = "Drill Ward 1";
export const WARD_2 = "Drill Ward 2";

/** BCM codes BCM9001 .. BCM9040 exist; each scenario uses its own. */
export const bcm = (n: number): string => `BCM9${String(n).padStart(3, "0")}`;

// ---------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------

export async function login(page: Page, who: Persona): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("รหัสพนักงาน / อีเมล").fill(who.code);
  await page.getByLabel("รหัสผ่าน", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "เข้าสู่ระบบ", exact: true }).click();
  await expect(page.getByText("หน้าหลัก").first()).toBeVisible();
}

/**
 * Logs in and waits until the reference snapshot has been stored locally, so a
 * later offline BCM search can work. Without a snapshot the device is also
 * treated as stale, which would add the staleness gate (a different drill).
 */
export async function loginAndWaitForSnapshot(page: Page, who: Persona): Promise<void> {
  await login(page, who);
  await expect
    // last_snapshot_at is written only after ALL snapshot sections are stored.
    .poll(() => hasMeta(page, "last_snapshot_at"), { message: "reference snapshot stored", timeout: 30_000 })
    .toBe(true);
  // Finding (E1): with registerType "prompt" the service worker installed on the
  // very first visit does not control that page until it is reloaded, so a
  // lazily loaded route (e.g. /borrow) fails offline in that first session. A
  // real device has normally been opened more than once; reload like it would.
  await page.evaluate(() => navigator.serviceWorker.ready);
  if (!(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)))) {
    await page.reload();
    await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
    await expect(page.getByText("หน้าหลัก").first()).toBeVisible();
  }
}

export async function hasMeta(page: Page, name: string): Promise<boolean> {
  return page.evaluate(
    (n) =>
      new Promise<boolean>((resolve) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => resolve(false);
        open.onsuccess = () => {
          const db = open.result;
          if (!db.objectStoreNames.contains("meta")) return resolve(false);
          const req = db.transaction("meta").objectStore("meta").get(n);
          req.onsuccess = () => resolve(req.result !== undefined);
          req.onerror = () => resolve(false);
        };
      }),
    name,
  );
}

export async function logoutViaUi(page: Page): Promise<void> {
  await page.getByRole("button", { name: "ออกจากระบบ" }).first().click();
  await expect(page).toHaveURL(/\/login/);
}

/** Client-side navigation (works offline: the app shell is already loaded). */
export async function goTo(page: Page, label: string): Promise<void> {
  await page.locator("aside").getByRole("link", { name: label, exact: false }).first().click();
}

export async function goOffline(context: BrowserContext, page: Page): Promise<void> {
  await context.setOffline(true);
  // The app marks itself offline from navigator.onLine or a failed request.
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
}

export async function goOnline(context: BrowserContext): Promise<void> {
  await context.setOffline(false);
}

/** Dismiss the full-screen staleness warning if it is showing. */
export async function ackStaleIfShown(page: Page): Promise<void> {
  const ack = page.getByRole("button", { name: "รับทราบและดำเนินการต่อ" });
  // The gate appears asynchronously (IndexedDB read), so wait briefly.
  try {
    await ack.waitFor({ state: "visible", timeout: 1_500 });
    await ack.click();
  } catch {
    /* not shown */
  }
}

/** Offline dispatch of one BCM code through the real form. */
export async function dispatchByBcm(page: Page, code: string, ward: string = WARD_1): Promise<void> {
  await goTo(page, "เบิก");
  await ackStaleIfShown(page);
  await page.getByPlaceholder("กรอกรหัส BCM").fill(code);
  await page.getByRole("button", { name: code, exact: true }).click();
  await ackStaleIfShown(page);
  await page.getByLabel(/หอผู้ป่วยที่รับเครื่อง/).selectOption({ label: ward });
  await page.getByRole("button", { name: /^(บันทึกการเบิก \(ในเครื่อง\)|ยืนยันการเบิก)$/ }).click();
}

export async function expectSavedLocally(page: Page): Promise<void> {
  await expect(page.getByText("บันทึกในเครื่องแล้ว — ยังไม่ได้ส่งเข้าระบบ")).toBeVisible();
}

/** Offline receipt of an open transaction picked from the local list. */
export async function receiveByBcm(page: Page, code: string, outcome: "usable" | "defective" = "usable"): Promise<void> {
  await goTo(page, "รับคืน");
  await ackStaleIfShown(page);
  await page.getByLabel("ค้นหารหัส BCM").fill(code);
  await page.getByRole("button", { name: new RegExp(code) }).click();
  await page.getByLabel(outcome === "usable" ? "พร้อมใช้งาน" : "ชำรุด").check();
  await page.getByRole("button", { name: "บันทึกการรับคืน (ในเครื่อง)" }).click();
}

// ---------------------------------------------------------------------------
// IndexedDB peeks (read/patch the real store the app uses)
// ---------------------------------------------------------------------------

export async function idbCount(page: Page, store: string): Promise<number> {
  return page.evaluate(
    (s) =>
      new Promise<number>((resolve) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => resolve(0);
        open.onsuccess = () => {
          const db = open.result;
          if (!db.objectStoreNames.contains(s)) return resolve(0);
          const req = db.transaction(s).objectStore(s).count();
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => resolve(0);
        };
      }),
    store,
  );
}

export async function outboxRecords(page: Page): Promise<Array<{ op_id: string; state: string; user_id: string; envelope: Record<string, unknown> }>> {
  return page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const req = open.result.transaction("outbox").objectStore("outbox").getAll();
          req.onsuccess = () => resolve(req.result as never);
          req.onerror = () => reject(req.error);
        };
      }),
  );
}

/** Rewrites an outbox envelope's local time (used to simulate a long-offline device). */
export async function backdateOutbox(page: Page, opId: string, daysAgo: number): Promise<void> {
  await page.evaluate(
    ({ id, days }) =>
      new Promise<void>((resolve, reject) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const tx = open.result.transaction("outbox", "readwrite");
          const store = tx.objectStore("outbox");
          const get = store.get(id);
          get.onsuccess = () => {
            const rec = get.result;
            rec.envelope.occurred_at_local = new Date(Date.now() - days * 86_400_000).toISOString();
            delete rec.envelope.clock_offset_ms;
            store.put(rec);
          };
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        };
      }),
    { id: opId, days: daysAgo },
  );
}

// ---------------------------------------------------------------------------
// Backend (API) helpers -- independent of the browser's offline switch
// ---------------------------------------------------------------------------

export async function apiContext(): Promise<APIRequestContext> {
  return pwRequest.newContext({ baseURL: API + "/" });
}

export async function apiLogin(api: APIRequestContext, who: Persona): Promise<string> {
  const res = await api.post("auth/login", { data: { identifier: who.code, password: PASSWORD } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).access_token as string;
}

export interface TxRow {
  id: string;
  status: string;
  returned_at: string | null;
  receipt_outcome: string | null;
  borrower_name?: string | null;
}

async function equipmentId(api: APIRequestContext, token: string, code: string): Promise<string> {
  const res = await api.get(`equipment/search/bcm?q=${encodeURIComponent(code)}&limit=5`, { headers: { Authorization: `Bearer ${token}` } });
  expect(res.ok()).toBeTruthy();
  const match = ((await res.json()) as Array<{ id: string; bcm_code: string }>).find((e) => e.bcm_code === code);
  expect(match, `equipment ${code} found`).toBeTruthy();
  return match!.id;
}

/** All transactions (dispatch events) for one BCM code. */
export async function transactionsFor(api: APIRequestContext, token: string, code: string): Promise<TxRow[]> {
  const id = await equipmentId(api, token, code);
  const res = await api.get(`transactions?equipment_id=${id}&limit=50`, { headers: { Authorization: `Bearer ${token}` } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).items as TxRow[];
}

export async function equipmentStatus(api: APIRequestContext, token: string, code: string): Promise<string> {
  const id = await equipmentId(api, token, code);
  const res = await api.get(`equipment/${id}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).status as string;
}

/** Creates a machine key for the read-only export API and returns a reader. */
export async function exportReader(api: APIRequestContext, adminToken: string) {
  const created = await api.post("export-keys", {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { name: `drill-${Date.now()}` },
  });
  expect(created.ok()).toBeTruthy();
  const key = (await created.json()).key as string;
  return async (): Promise<Array<{ seq: number; event_type: string; transaction_id: string; equipment: { bcm_code: string } }>> => {
    const res = await api.get("export/events?after=0&limit=500", { headers: { "X-API-Key": key } });
    expect(res.ok()).toBeTruthy();
    return (await res.json()).events;
  };
}
