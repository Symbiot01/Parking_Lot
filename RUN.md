# Parking Lot Management — Run Guide

FastAPI + SQLite backend and React (Vite + Tailwind) frontend with **Worker** and **Customer** dashboards.

## Docker (recommended)

```bash
# from repo root
cp .env.example .env   # optional overrides
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API / docs: http://localhost:8000/docs
- Worker login: `admin@example.com` / `AdminPass123!` (override via `.env`)

SQLite data is stored in the `parking_data` Docker volume.

### Images alone

```bash
docker build -t parking-backend ./backend
docker build -t parking-frontend --build-arg VITE_API_URL=http://localhost:8000 ./frontend

docker run --rm -p 8000:8000 -v parking_data:/app/data parking-backend
docker run --rm -p 3000:80 parking-frontend
```

## Local quick start (without Docker)

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; defaults work for local demo
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

API docs: http://127.0.0.1:8000/docs

> If port 8000 is busy, use `--port 8001` and set `VITE_API_URL=http://127.0.0.1:8001` in `frontend/.env`.

On startup the app creates SQLite tables and seeds:

- 3 levels × 10 TW + 10 FW slots (closest = `*-001`)
- Fee policies
- Admin user: `admin@example.com` / `AdminPass123!`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

- **Worker dashboard** — login as admin
- **Customer dashboard** — register a new account (PUBLIC role only)

## Allocation rule

Earliest floor first, then lowest `distance_from_entry` (closest to entry). No random allotment.

## Security notes

- Passwords hashed with Argon2
- JWT bearer auth on all parking/booking APIs
- Register always creates `PUBLIC` users (cannot self-promote to ADMIN)
- Customer availability API returns booleans only (no lot numbers)
- Unlock is admin-only or owner of the open stay / booking
- Do not commit `.env` files; use `.env.example` / compose env vars instead

See the design document in [README.md](./README.md) for HLD/LLD details (originally Django-oriented; implementation is FastAPI + SQLite as requested).
