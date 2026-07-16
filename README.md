# Medical Equipment Pool

ระบบรับ-ส่งเครื่องมือแพทย์ (Hospital Medical Equipment Borrow/Return Pool) — ทดแทนระบบเดิมที่สร้างด้วย AppSheet ด้วยสถาปัตยกรรม **React (PWA) + FastAPI + PostgreSQL + Redis** เพื่อรองรับข้อมูลหลักแสนรายการและผู้ใช้งานพร้อมกันหลายสิบ-ร้อยคน โดยยังคงประสบการณ์ใช้งานง่าย มือถือ-เดสก์ท็อป, Scan QR เป็นหลัก, และรองรับ Offline

📄 เอกสารฉบับเต็ม (System Architecture, ER Diagram, API Spec, UI Mockup, Deployment Guide, Security, Testing Plan, Roadmap ฯลฯ) อยู่ใน [`docs/`](./docs).

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + TypeScript + Vite, TailwindCSS, TanStack Query, Zustand, PWA (Workbox) |
| Backend | FastAPI (async), SQLAlchemy 2.0, Alembic |
| Database | PostgreSQL 16 (+ `pg_trgm` fuzzy search) |
| Cache | Redis (cache-aside, rate-limit) |
| Object storage | MinIO (S3-compatible) |
| Deployment | Docker Compose, Nginx |

## Quick start (local)

```bash
cp .env.example .env        # edit secrets
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed
```

- Frontend: http://localhost
- Backend Swagger UI: http://localhost:8000/api/docs
- Default admin login (after seeding): `ADMIN001` / `Admin@12345`

## Running backend/frontend without Docker (dev)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://mep_user:mep_password@localhost:5432/mep_db
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

## Tests

```bash
cd backend && source .venv/bin/activate && pytest
```

Backend tests run against an in-memory SQLite database (fast, no external dependency) and cover auth, RBAC, equipment CRUD/search, and the borrow/return flow including the double-borrow race guard. See [`docs/09-testing-plan.md`](./docs/09-testing-plan.md) for the full test strategy including Postgres integration/load testing.

## Project layout

See [`docs/05-folder-structure.md`](./docs/05-folder-structure.md) for the full breakdown of `backend/` and `frontend/`.

## Documentation index

1. [System Architecture](./docs/01-architecture.md)
2. [Database Schema & ER Diagram](./docs/02-database-schema.md)
3. [API Specification](./docs/03-api-specification.md)
4. [UI Mockups](./docs/04-ui-mockups.md)
5. [Folder Structure](./docs/05-folder-structure.md)
6. [Deployment Guide](./docs/06-deployment-guide.md)
7. [Performance Optimization](./docs/07-performance-optimization.md)
8. [Security Best Practices](./docs/08-security.md)
9. [Testing Plan](./docs/09-testing-plan.md)
10. [Future Roadmap](./docs/10-roadmap.md)

## License

Internal hospital tooling — no license file included; adapt as needed for your organization.
