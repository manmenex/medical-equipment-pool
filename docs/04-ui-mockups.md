# UI Mockups (Wireframe Description)

> **Status: Legacy design reference.** Some proposals and scale targets in
> this document predate confirmed guardrails and may be superseded. Use
> `AGENTS.md`, `PROJECT_PLAYBOOK.md`, `ARCHITECTURE_DECISIONS.md`, and the
> consolidated implementation plan for current authority.

หลักการออกแบบ: **ใช้งานด้วยมือเดียว, กดน้อยที่สุด, Scan QR เป็นทางหลัก, Bottom Navigation บนมือถือ, Sidebar บนจอใหญ่, รองรับ Dark Mode**

Layout breakpoints: `mobile < 640px` (bottom nav, single column) · `tablet 640–1024px` (2 column, collapsible sidebar) · `desktop > 1024px` (persistent sidebar, multi-column, data tables)

## 1. Login
```
┌──────────────────────────────┐
│         [Hospital Logo]       │
│     Medical Equipment Pool    │
│                                │
│  Employee Code / Email        │
│  [______________________]     │
│  Password                     │
│  [______________________] 👁  │
│                                │
│        [   Sign In   ]        │
│  Remember me      Dark 🌙      │
└──────────────────────────────┘
```
- Single primary action, autofocus first field, biometric/PIN quick-unlock on repeat visits (PWA local storage of refresh token)

## 2. Dashboard (Home)
```
┌ ☰  Medical Equipment Pool        🔔3  👤 ▾ ┐
├──────────────────────────────────────────────┤
│ [Total 1,240] [Available 812] [Borrowed 298]  │
│ [Repair 42] [PM 18] [Calibration 9]           │
├──────────────────────────────────────────────┤
│  PM Due Soon (7d)      │  CAL Due Soon (7d)   │
│  • Infusion Pump #123  │  • ECG #45           │
│  • ...                 │  • ...               │
├──────────────────────────────────────────────┤
│  Borrow Trend (30d line chart)                │
├──────────────────────────────────────────────┤
│  Top Borrowed Equipment (bar chart, top 10)   │
└──────────────────────────────────────────────┘
[🏠 Home] [🔍 Search] [📷 Scan] [📋 History] [☰ More]   ← bottom nav (mobile)
```
- Stat tiles are tap-through filters into Equipment List
- Live-updating via SSE (badge pulses on change, no full reload)

## 3. Equipment List / Search
```
┌ ← Equipment                          🔍 [   search box   ] ┐
│ Filter: [Status ▾] [Department ▾] [Category ▾]  Sort: [▾]  │
├──────────────────────────────────────────────────────────┤
│ ▣ AST-00123  Infusion Pump   Ward 5A   🟢 Available        │
│ ▣ AST-00124  ECG Monitor     ICU       🔵 Borrowed         │
│ ▣ AST-00125  Ventilator      OR-1      🟠 Repair           │
│  ... (virtualized infinite-scroll list, 60fps at 500k rows)│
└──────────────────────────────────────────────────────────┘
```
- Search box debounced 150ms, results stream in < 300ms; instant client-side highlight of matched substring
- Tap row → Equipment Detail (status timeline, QR, PM/CAL dates, borrow history)

## 4. Borrow (One-Click flow)
```
Step 1            Step 2                Step 3
┌───────────┐    ┌───────────────┐    ┌───────────────┐
│ 📷 Scan QR │ →  │ Confirm Item   │ →  │ ✅ Borrowed    │
│  or manual │    │ Borrower name  │    │ Transaction #  │
│  search    │    │ Ward, Phone    │    │ auto-generated │
│            │    │ Pickup/Dropoff │    │                │
│            │    │ [ Confirm ]    │    │                │
└───────────┘    └───────────────┘    └───────────────┘
```
- If scanned item is NOT Available → immediate red toast + shows current status/last borrower, blocks submission
- Ward/borrower fields remember last-used value (localStorage) → true "one-click" for repeat borrows from same ward
- Big touch targets (min 44×44px), works one-handed holding phone

## 5. Return
```
┌ ← Return                                    ┐
│  📷 Scan QR                                  │
│  Item: Infusion Pump AST-00123               │
│  Borrowed by: พยาบาล สมหญิง (Ward 5A, 2 days) │
│                                               │
│  Condition:                                  │
│  ( ) Available  ( ) Cleaning  ( ) PM         │
│  ( ) Calibration  ( ) Repair                 │
│                                               │
│  📷 Photo (optional)   ✍️ Signature           │
│  Notes: [____________________]               │
│                                               │
│         [   Confirm Return   ]               │
└───────────────────────────────────────────────┘
```
- Returned_at timestamp auto-recorded server-side (not client clock, avoids tampering)
- Selecting a non-Available condition auto-routes equipment status + creates a task visible to Biomedical Engineer queue

## 6. Report
```
┌ ← Reports                                    ┐
│ Type: [Borrow Frequency ▾]  Range: [30d ▾]    │
│ [Chart: bar/line]                             │
│ Export: [Excel] [PDF] [CSV]                   │
└────────────────────────────────────────────────┘
```

## 7. Admin
```
┌ Admin                                         ┐
│ Tabs: Users | Departments | Wards | Locations │
│       | Categories | Audit Log                │
│ [+ Add]  [table with inline edit]             │
└────────────────────────────────────────────────┘
```

## 8. Settings
```
Theme: (•) Light ( ) Dark ( ) System
Notification channels: [✓] Email  [ ] LINE (future)  [ ] Teams (future)
Offline data: [Clear cache]  Last sync: 09:41
Language: [ไทย ▾]
```

## Design tokens (used across the app)
- Status colors: Available `#16A34A` green · Borrowed `#2563EB` blue · Cleaning `#0EA5E9` cyan · PM `#CA8A04` amber · Calibration `#7C3AED` violet · Repair `#EA580C` orange · Out of Service `#6B7280` gray · Lost `#DC2626` red
- Typography: system font stack (`-apple-system, "Noto Sans Thai", sans-serif`) for correct Thai rendering
- Both light and dark palettes defined as CSS variables in `frontend/src/index.css` (see Tailwind config)
