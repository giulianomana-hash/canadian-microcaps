# SedarWatchlist

A full-stack financial dashboard plugin for tracking Canadian microcap companies (<$50M market cap).

## Architecture

```
canadian-microcaps/
├── frontend/      # React + Vite plugin UI (<SedarWatchlist /> component)
├── backend/       # FastAPI service backed by Supabase
└── supabase/      # Postgres schema
```

The frontend ships as a self-contained plugin component (`<SedarWatchlist pluginConfig={...} />`) that can be dropped into a future shell app. It talks to the FastAPI backend over HTTP, which in turn persists data in Supabase Postgres.

## Quick start

### 1. Database

Create a Supabase project and run `supabase/schema.sql` in the SQL editor. Grab the project URL and service-role (or anon) key.

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in SUPABASE_URL and SUPABASE_KEY
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000` with interactive docs at `/docs`.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env   # defaults point at http://localhost:8000
npm run dev
```

Vite serves the dev app at `http://localhost:5173`.

## Routes

| Method | Path                       | Purpose                       |
| ------ | -------------------------- | ----------------------------- |
| GET    | `/api/watchlist`           | List all watchlist entries    |
| POST   | `/api/watchlist`           | Add a company to the watchlist |
| DELETE | `/api/watchlist/{id}`      | Remove a watchlist entry      |
| GET    | `/api/filings`             | List cached filings (newest first) |

## Embedding the plugin

```jsx
import SedarWatchlist from "./components/SedarWatchlist";

<SedarWatchlist
  pluginConfig={{
    apiBaseUrl: "http://localhost:8000",
    userId: "demo-user",
    marketCapCeiling: 50_000_000,
  }}
/>
```
