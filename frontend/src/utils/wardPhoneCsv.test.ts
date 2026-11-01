import { describe, expect, it } from "vitest";

import { parseWardPhoneCsv } from "@/utils/wardPhoneCsv";

describe("parseWardPhoneCsv", () => {
  it("parses Thai text with a UTF-8 BOM and ignores the extra nsmart_department column", () => {
    const r = parseWardPhoneCsv("﻿ward_name,nsmart_department,phone\r\nหอผู้ป่วยใน 1,อายุรกรรม,1234\n\"หอ, พิเศษ\",x,5678\n");
    expect(r.error).toBeNull();
    expect(r.rows).toEqual([
      { ward_name: "หอผู้ป่วยใน 1", phone: "1234" },
      { ward_name: "หอ, พิเศษ", phone: "5678" },
    ]);
  });
  it("rejects a missing header, empty input and more than 500 rows", () => {
    expect(parseWardPhoneCsv("a,b\n1,2").error).toMatch(/ward_name/);
    expect(parseWardPhoneCsv("").error).not.toBeNull();
    const big = "ward_name,phone\n" + Array.from({ length: 501 }, (_, i) => `w${i},1`).join("\n");
    expect(parseWardPhoneCsv(big).error).toMatch(/500/);
    const ok = "ward_name,phone\n" + Array.from({ length: 500 }, (_, i) => `w${i},1`).join("\n");
    expect(parseWardPhoneCsv(ok).rows).toHaveLength(500);
  });
});
