# Future Roadmap

## Phase 1 — MVP (this build)
Auth/RBAC · Equipment CRUD + QR generation/scan · Borrow/Return core flow · Real-time-ish Dashboard (SSE) · Instant search · Reports export (CSV/XLSX) · Audit log · Docker Compose deployment · Dark mode · Responsive/PWA shell

## Phase 2 — Offline & Notifications hardening
- Full offline-first borrow/return with IndexedDB queue + background sync + conflict resolution UI
- Web Push notifications (PM/CAL/Overdue/Broken) in-browser
- Email notifications (SMTP) fully wired to scheduler
- Photo capture + signature capture on Return, stored to object storage
- Camera OCR to auto-read asset number/serial from a label when QR is missing/damaged

## Phase 3 — Integrations
- LINE Notify integration for ward-level alerts
- Microsoft Teams webhook notifications
- RFID tag read/write support alongside QR (hardware integration point already reserved in schema: `equipment.rfid_tag`)
- HIS/ERP integration (HL7/FHIR or REST) for department/asset master-data sync

## Phase 4 — Advanced Analytics
- SLA Dashboard (turnaround time per ward, repair SLA compliance)
- KPI Dashboard (utilization %, downtime %, cost per repair)
- Heat map of equipment usage by ward/department/time-of-day
- Machine History Timeline (rich visual per-asset lifecycle view)
- Predictive PM: statistical/ML model estimating failure risk from usage + repair history, feeding a "at-risk" queue for Biomedical Engineering
- AI usage-pattern analysis: anomaly detection on borrow frequency, auto-flag likely-lost equipment

## Phase 5 — Collaboration & Scale
- In-app chat/ticketing for equipment problem reports (ties into Repair workflow + audit trail)
- Favorite Equipment / quick-access list per user role
- Multi-hospital / multi-site tenancy (dataset partitioned by `site_id`)
- Kubernetes deployment option + read replicas + horizontal Postgres sharding if a hospital network scenario exceeds single-primary capacity
- Native mobile wrapper (Capacitor) if app-store distribution becomes a hospital IT requirement — reuses the same React codebase, no rewrite

## Explicitly deferred (per original spec, marked "Future" by requester)
- RFID (Phase 3)
- LINE Notify (Phase 3)
- Microsoft Teams (Phase 3)
