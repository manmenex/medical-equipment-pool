# Folder Structure

> **Status: Legacy design reference.** Some proposals and scale targets in
> this document predate confirmed guardrails and may be superseded. Use
> `AGENTS.md`, `PROJECT_PLAYBOOK.md`, `ARCHITECTURE_DECISIONS.md`, and the
> consolidated implementation plan for current authority.

```
medical-equipment-pool/
├── docs/                          # This documentation set
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── README.md
│
├── backend/                       # FastAPI service
│   ├── app/
│   │   ├── main.py                # app factory, middleware, router include
│   │   ├── core/
│   │   │   ├── config.py          # Pydantic Settings (env-driven)
│   │   │   ├── security.py        # JWT, password hashing, RBAC deps
│   │   │   ├── logging.py
│   │   │   └── redis.py           # Redis client + cache helpers
│   │   ├── db/
│   │   │   ├── base.py            # declarative Base, import registry
│   │   │   └── session.py         # async engine + sessionmaker + get_db dep
│   │   ├── models/                # SQLAlchemy ORM models (one file per aggregate)
│   │   │   ├── user.py, equipment.py, transaction.py, master_data.py,
│   │   │   │   audit.py, notification.py
│   │   ├── schemas/                # Pydantic request/response DTOs
│   │   ├── crud/                   # DB access functions (repository layer)
│   │   ├── services/                # business logic (borrow_service, dashboard_service, qr_service, report_service, notification_service)
│   │   ├── api/v1/                 # route modules, one per resource
│   │   │   ├── router.py           # aggregates all routers
│   │   │   ├── auth.py, equipment.py, borrow.py, transactions.py,
│   │   │   │   dashboard.py, reports.py, users.py, master_data.py,
│   │   │   │   audit.py, notifications.py
│   │   ├── utils/
│   │   └── worker/                 # APScheduler jobs (pm_cal_reminder, overdue_check)
│   ├── alembic/                    # migrations
│   ├── tests/                      # pytest (unit + integration)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── pytest.ini
│
└── frontend/                       # React + TypeScript PWA
    ├── src/
    │   ├── main.tsx, App.tsx, router.tsx
    │   ├── pages/                  # Login, Dashboard, EquipmentList, EquipmentDetail,
    │   │                           # Borrow, Return, Report, Admin, Settings
    │   ├── components/             # shared UI (StatCard, QRScanner, StatusBadge, DataTable, ...)
    │   ├── layouts/                # AppShell (sidebar/bottom-nav), AuthLayout
    │   ├── services/                # api client (axios/fetch wrapper), auth.ts, equipment.ts, ...
    │   ├── store/                   # zustand stores (auth, ui/theme, offlineQueue)
    │   ├── hooks/                    # useEquipmentSearch, useDashboardStream, ...
    │   ├── types/                    # shared TS types mirroring backend schemas
    │   └── styles/
    ├── public/
    │   ├── manifest.webmanifest
    │   └── icons/
    ├── index.html
    ├── vite.config.ts               # incl. VitePWA plugin config
    ├── tailwind.config.ts
    ├── package.json
    └── Dockerfile
```

Rationale: backend follows a **layered architecture** (`api → services → crud → models`) so business rules (e.g. "borrow only if Available", "one active borrow per equipment") live in `services/`, testable independent of HTTP or DB wiring. Frontend follows **feature-colocation within pages/** with shared primitives in `components/`, keeping bundle splitting natural per route.
