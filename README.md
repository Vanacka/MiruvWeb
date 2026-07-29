# MiruvWeb

Interní webová aplikace se správou uživatelů, evidencí pohonných hmot, dovolených a výkonu, včetně notifikací.

## Tech stack

- **Backend:** FastAPI, SQLAlchemy, SQLite
- **Frontend:** Vue 3, TypeScript, Vite, Pinia

## Spuštění přes Docker Compose

```bash
docker compose up --build
```

- Backend běží na `http://localhost:8000`
- Frontend běží na `http://localhost:3000`

Výchozí admin účet (lze přepsat přes env proměnné, viz `docker-compose.yml`):

- uživatel: `mirek`
- heslo: `changeme123`

## Lokální vývoj bez Dockeru

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

## Konfigurace

Backend čte nastavení z proměnných prostředí (viz `docker-compose.yml`):

- `CORS_ORIGINS` – povolené originy pro CORS
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` – přihlašovací údaje výchozího admina
- `SECRET_KEY` – tajný klíč pro podepisování JWT (v produkci nutné změnit)