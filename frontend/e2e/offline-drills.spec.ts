import { expect, test } from "@playwright/test";

import {
  USERS,
  apiContext,
  apiLogin,
  backdateOutbox,
  bcm,
  dispatchByBcm,
  equipmentStatus,
  expectSavedLocally,
  exportReader,
  goOffline,
  goOnline,
  goTo,
  login,
  loginAndWaitForSnapshot,
  logoutViaUi,
  outboxRecords,
  receiveByBcm,
  transactionsFor,
} from "./support/helpers";
import {
  PASSWORD,
  applyReviewItemNow,
  auditActorsFor,
  dismissReviewItem,
  reviewItem,
  setMeta,
  userIdOf,
} from "./support/more";

// PR25E E1 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 17, items 17/18):
// automated browser drills against the real API. Evidence class: local
// rehearsal on throwaway SQLite with synthetic data -- not UAT, not
// PostgreSQL evidence, not a real-device test. Each scenario uses equipment
// of its own (BCM9001 ..) so scenarios do not influence each other.

test.describe.configure({ mode: "serial" });

const PENDING = /รอส่ง \d+ รายการ/;

test("a: offline dispatch survives reload and syncs exactly once", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const code = bcm(1);
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);
  const readEvents = await exportReader(api, adminToken);

  await loginAndWaitForSnapshot(page, USERS.poolA);
  await goOffline(context, page);

  await dispatchByBcm(page, code);
  await expectSavedLocally(page);
  await expect(page.getByText("รอส่ง 1 รายการ")).toBeVisible();

  // Reload while still offline: the shell loads from the service worker and
  // the queued operation is still there.
  await page.reload();
  await expect(page.getByText("รอส่ง 1 รายการ")).toBeVisible();
  expect(await outboxRecords(page)).toHaveLength(1);

  // Nothing reached the server yet.
  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");

  await goOnline(context);
  await expect(page.getByText(PENDING)).toHaveCount(0, { timeout: 60_000 });

  expect(await equipmentStatus(api, adminToken, code)).toBe("issued_to_ward");
  expect(await transactionsFor(api, adminToken, code)).toHaveLength(1);
  const events = (await readEvents()).filter((e) => e.equipment.bcm_code === code);
  expect(events.map((e) => e.event_type)).toEqual(["dispatch"]);
  await context.close();
});

test("b: two devices dispatch the same equipment offline -> one applied, one conflict, reviewer dismisses", async ({
  browser,
}) => {
  const code = bcm(2);
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);

  const ctx1 = await browser.newContext();
  const ctx2 = await browser.newContext();
  const dev1 = await ctx1.newPage();
  const dev2 = await ctx2.newPage();
  await loginAndWaitForSnapshot(dev1, USERS.poolA);
  await loginAndWaitForSnapshot(dev2, USERS.poolB);

  await goOffline(ctx1, dev1);
  await goOffline(ctx2, dev2);
  await dispatchByBcm(dev1, code, "Drill Ward 1");
  await expectSavedLocally(dev1);
  await dispatchByBcm(dev2, code, "Drill Ward 2");
  await expectSavedLocally(dev2);

  // Device 1 reaches the server first and wins.
  await goOnline(ctx1);
  await expect(dev1.getByText(PENDING)).toHaveCount(0, { timeout: 60_000 });
  expect(await equipmentStatus(api, adminToken, code)).toBe("issued_to_ward");

  // Device 2 arrives second: a conflict is recorded, never a second dispatch.
  await goOnline(ctx2);
  await expect(dev2.getByText("รอเจ้าหน้าที่ตรวจสอบ 1 รายการ")).toBeVisible({ timeout: 60_000 });
  expect(await transactionsFor(api, adminToken, code)).toHaveLength(1);

  // Reviewer resolves it on the review page.
  const ctx3 = await browser.newContext();
  const reviewer = await ctx3.newPage();
  await login(reviewer, USERS.admin);
  await goTo(reviewer, "ตรวจสอบรายการออฟไลน์");
  await expect(reviewer.getByTestId("sync-review-item")).toHaveCount(1);
  await dismissReviewItem(reviewer, code);
  await expect(reviewer.getByText("ไม่มีรายการที่รอตรวจสอบ")).toBeVisible();

  expect(await transactionsFor(api, adminToken, code)).toHaveLength(1);
  expect(await equipmentStatus(api, adminToken, code)).toBe("issued_to_ward");
  await ctx1.close();
  await ctx2.close();
  await ctx3.close();
});

test("c: offline dispatch then offline receipt -> sync order respected, both applied", async ({ browser }) => {
  const code = bcm(3);
  const context = await browser.newContext();
  const page = await context.newPage();
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);
  const readEvents = await exportReader(api, adminToken);

  await loginAndWaitForSnapshot(page, USERS.poolA);
  await goOffline(context, page);
  await dispatchByBcm(page, code);
  await expectSavedLocally(page);
  await receiveByBcm(page, code, "usable");
  await expectSavedLocally(page);
  await expect(page.getByText("รอส่ง 2 รายการ")).toBeVisible();

  await goOnline(context);
  await expect(page.getByText(PENDING)).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByText(/รอเจ้าหน้าที่ตรวจสอบ/)).toHaveCount(0);

  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");
  const txs = await transactionsFor(api, adminToken, code);
  expect(txs).toHaveLength(1);
  expect(txs[0].receipt_outcome).toBe("usable");
  expect(txs[0].returned_at).not.toBeNull();
  const types = (await readEvents()).filter((e) => e.equipment.bcm_code === code).map((e) => e.event_type);
  expect(types).toEqual(["dispatch", "receipt"]);
  await context.close();
});

test("d: dispatch older than 7 days -> OP_TOO_OLD in review -> apply now", async ({ browser }) => {
  const code = bcm(4);
  const context = await browser.newContext();
  const page = await context.newPage();
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);

  await loginAndWaitForSnapshot(page, USERS.poolA);
  await goOffline(context, page);
  await dispatchByBcm(page, code);
  await expectSavedLocally(page);
  const [rec] = await outboxRecords(page);
  // Simulate a device that was offline for 8 days by rewriting the stored
  // envelope's local time (the clock-offset correction is dropped with it).
  await backdateOutbox(page, rec.op_id, 8);

  await goOnline(context);
  await expect(page.getByText("รอเจ้าหน้าที่ตรวจสอบ 1 รายการ")).toBeVisible({ timeout: 60_000 });
  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");

  const ctx2 = await browser.newContext();
  const reviewer = await ctx2.newPage();
  await login(reviewer, USERS.admin);
  await goTo(reviewer, "ตรวจสอบรายการออฟไลน์");
  await expect(reviewItem(reviewer, "OP_TOO_OLD")).toHaveCount(1);
  await applyReviewItemNow(reviewer, "OP_TOO_OLD");

  expect(await equipmentStatus(api, adminToken, code)).toBe("issued_to_ward");
  const txs = await transactionsFor(api, adminToken, code);
  expect(txs).toHaveLength(1);
  // Recorded at the original (8 days ago) time, not at resolution time.
  const borrowedAt = (txs[0] as unknown as { borrowed_at: string }).borrowed_at;
  expect((Date.now() - new Date(borrowedAt).getTime()) / 86_400_000).toBeGreaterThan(7);
  await context.close();
  await ctx2.close();
});

test("e: shared device -> user B adopts user A's queued op with password", async ({ browser }) => {
  const code = bcm(5);
  const context = await browser.newContext();
  const page = await context.newPage();
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);
  const idA = await userIdOf(api, adminToken, USERS.poolA);
  const idB = await userIdOf(api, adminToken, USERS.poolB);

  await loginAndWaitForSnapshot(page, USERS.poolA);
  await goOffline(context, page);
  await dispatchByBcm(page, code);
  await expectSavedLocally(page);
  await logoutViaUi(page);
  // The queued op stays on the device after logout.
  expect(await outboxRecords(page)).toHaveLength(1);

  await goOnline(context);
  await login(page, USERS.poolB);
  // B's own sync loop does not send A's operation.
  await page.waitForTimeout(3_000);
  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");

  await goTo(page, "ตรวจสอบรายการออฟไลน์");
  const group = page.getByTestId("other-user-group");
  await expect(group).toContainText("Drill Pool A");
  await group.getByRole("button", { name: "ส่งแทน" }).click();
  const dialog = page.getByRole("dialog", { name: "ยืนยันการส่งแทน" });
  await dialog.getByLabel("ยืนยันรหัสผ่านของคุณ").fill(PASSWORD);
  await dialog.getByRole("button", { name: "ยืนยันและส่ง" }).click();
  await expect(page.getByTestId("adopt-summary")).toContainText("ส่งสำเร็จ 1 รายการ");

  expect(await equipmentStatus(api, adminToken, code)).toBe("issued_to_ward");
  const [tx] = await transactionsFor(api, adminToken, code);
  // Recorded operator is A; the audit actor for the applied op is B.
  for (const [operator, expected] of [
    [idA, true],
    [idB, false],
  ] as const) {
    const res = await api.get(`reports/issue?operator_id=${operator}&limit=200`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    expect(res.ok()).toBeTruthy();
    const ids = ((await res.json()).items as Array<{ id: string }>).map((r) => r.id);
    expect(ids.includes(tx.id)).toBe(expected);
  }
  const audit = await auditActorsFor(api, adminToken, tx.id);
  expect(audit.length).toBeGreaterThan(0);
  expect(audit.some((r) => r.user_id === idB)).toBe(true);
  expect(audit.some((r) => r.user_id === idA)).toBe(false);
  await context.close();
});

test("g: staleness warning after 4 hours requires acknowledgement and stays as a banner", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginAndWaitForSnapshot(page, USERS.poolA);
  await setMeta(page, "last_snapshot_at", Date.now() - 5 * 3_600_000);
  await goOffline(context, page);
  await page.reload();
  await goTo(page, "เบิก");
  const gate = page.getByRole("alertdialog");
  await expect(gate).toContainText("ข้อมูลในเครื่องอาจล้าสมัย");
  await gate.getByRole("button", { name: "รับทราบและดำเนินการต่อ" }).click();
  await expect(page.getByRole("status").filter({ hasText: "ไม่ได้ซิงค์มานานกว่า 4 ชั่วโมง" })).toBeVisible();
  await context.close();
});

test("f: outdated envelope version -> CLIENT_TOO_OLD keeps the queue and asks for an update", async ({ browser }) => {
  const code = bcm(6);
  const context = await browser.newContext();
  const page = await context.newPage();
  const api = await apiContext();
  const adminToken = await apiLogin(api, USERS.admin);

  await loginAndWaitForSnapshot(page, USERS.poolA);
  await goOffline(context, page);
  await dispatchByBcm(page, code);
  await expectSavedLocally(page);
  const [rec] = await outboxRecords(page);
  // Simulate an old installed app: its queued envelope predates the version
  // the server still accepts (MIN_SUPPORTED_ENVELOPE_VERSION = 1).
  await page.evaluate(
    (id) =>
      new Promise<void>((resolve, reject) => {
        const open = indexedDB.open("mep-offline");
        open.onerror = () => reject(open.error);
        open.onsuccess = () => {
          const tx = open.result.transaction("outbox", "readwrite");
          const store = tx.objectStore("outbox");
          const get = store.get(id);
          get.onsuccess = () => {
            const r = get.result;
            r.envelope.envelope_version = 0;
            store.put(r);
          };
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        };
      }),
    rec.op_id,
  );

  await goOnline(context);
  await expect(page.getByText("ต้องอัปเดตแอปก่อนส่งข้อมูลต่อ")).toBeVisible({ timeout: 60_000 });
  // Nothing was applied and nothing was lost.
  expect(await outboxRecords(page)).toHaveLength(1);
  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");
  expect(await transactionsFor(api, adminToken, code)).toHaveLength(0);
  // For a required update the reload must NOT be blocked by pending rows (the
  // queue can only drain after the reload), and the queue survives it.
  const reloaded = page.waitForEvent("load");
  await page.getByRole("button", { name: "อัปเดตและรีโหลด" }).click();
  await reloaded;
  await expect(page.getByText("หน้าหลัก").first()).toBeVisible();
  expect(await outboxRecords(page)).toHaveLength(1);
  expect(await equipmentStatus(api, adminToken, code)).toBe("available_at_pool");
  await context.close();
});
