# Diecasting AI Lead Hunter

A B2B **AI customer-search system for the metal die-casting industry**.

It discovers die-casting manufacturers / OEMs from the web, stores them as
**company leads** in PostgreSQL, and uses the **OpenAI API** to score each lead's
fit and surface buying-intent signals — so a sales team can focus on the
companies most likely to need die-casting services.

> **Status:** Phase 1 (backend MVP). No frontend is included.

---

## Tech stack

| Layer        | Choice                                            |
|--------------|---------------------------------------------------|
| Web framework| FastAPI (Python 3.11)                             |
| Database     | PostgreSQL (+ SQLAlchemy 2.x ORM)                 |
| AI           | OpenAI Chat Completions API                       |
| Crawler      | Playwright (headless Chromium)                    |
| Deployment   | Docker + docker-compose                           |

---

## Features (Phase 1)

1. **Project structure** — clean, package-based FastAPI layout.
2. **Database models** — SQLAlchemy `CompanyLead` model + session/engine setup.
3. **Company Lead table** — `company_leads` with firmographics + AI-enrichment columns.
4. **AI analysis module** — `app/ai/analyzer.py` scores relevance (0–100), flags
   relevance, writes a summary and extracts fit/intent signals.
5. **Crawler module** — `app/crawler/crawler.py` searches the web and extracts
   lightweight company signals.
6. **REST API** — CRUD for leads plus `POST /leads/ingest` (crawl → persist) and
   `POST /leads/{id}/analyze` (run AI enrichment).
7. **Local & Docker run environments** — venv + `requirements.txt`, plus
   `Dockerfile` / `docker-compose.yml`.

---

## Project structure

```
diecasting-ai-lead-hunter/
├── app/
│   ├── main.py            # FastAPI app, lifespan, health, CORS
│   ├── config.py          # pydantic-settings (env / .env)
│   ├── database.py        # engine, SessionLocal, Base, get_db
│   ├── models/
│   │   └── lead.py        # CompanyLead ORM model
│   ├── schemas/
│   │   └── lead.py        # Pydantic request/response models
│   ├── crud/
│   │   └── leads.py       # CRUD operations
│   ├── routers/
│   │   └── leads.py       # REST endpoints (+ ingest, analyze)
│   ├── ai/
│   │   └── analyzer.py    # OpenAI analysis module
│   └── crawler/
│       └── crawler.py     # Playwright crawler
├── scripts/
│   └── init_db.py         # create_all helper
├── tests/
│   └── test_main.py       # API smoke tests (SQLite)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── .env.example
```

---

## Quick start (local, without Docker)

### 1. Prerequisites
- Python 3.11+
- A running PostgreSQL instance (or use Docker Compose below)

### 2. Create a virtual environment & install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# edit .env and set DATABASE_URL, OPENAI_API_KEY, etc.
```

### 4. Create the database schema

```bash
python scripts/init_db.py
```

### 5. (Optional) install Playwright browsers — needed for `/leads/ingest`

```bash
playwright install --with-deps chromium
```

### 6. Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

Open the interactive docs at <http://localhost:8000/docs>.

---

## Quick start (Docker)

```bash
# Provide your OpenAI key (used by docker-compose)
export OPENAI_API_KEY=sk-...

# Build & start Postgres + API
docker compose up --build
```

The API will be available at <http://localhost:8000/docs>. The entrypoint
auto-creates the tables on startup.

---

## Environment variables

| Variable            | Default                              | Description                              |
|---------------------|--------------------------------------|------------------------------------------|
| `APP_NAME`          | `diecasting-ai-lead-hunter`          | App title                               |
| `DEBUG`             | `false`                             | FastAPI debug mode                      |
| `DATABASE_URL`      | *(built from parts)*                | Full SQLAlchemy DB URL (overrides parts)|
| `POSTGRES_*`        | `localhost:5432/postgres/leadhunter`| Individual DB connection parts          |
| `OPENAI_API_KEY`    | —                                   | **Required** for AI analysis            |
| `OPENAI_MODEL`      | `gpt-4o-mini`                       | Chat model used for analysis            |
| `CRAWLER_HEADLESS`  | `true`                              | Run Chromium headless                  |
| `CRAWLER_MAX_PAGES` | `50`                                | Crawl budget                            |

---

## API reference

Base URL: `http://localhost:8000`

| Method | Path                     | Description                                      |
|--------|--------------------------|--------------------------------------------------|
| GET    | `/health`                | Health check                                     |
| GET    | `/leads`                 | List leads (`?relevant_only=true` to filter)     |
| POST   | `/leads`                 | Create a lead                                    |
| GET    | `/leads/{id}`            | Get a lead by id                                 |
| PATCH  | `/leads/{id}`            | Partially update a lead                          |
| DELETE | `/leads/{id}`            | Delete a lead                                    |
| POST   | `/leads/ingest`          | Crawl the web and persist new leads              |
| POST   | `/leads/{id}/analyze`    | Run AI enrichment on a lead                      |

### Example: create a lead

```bash
curl -X POST http://localhost:8000/leads \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Die Casting Co","website":"https://acme.example.com","industry":"Die casting"}'
```

### Example: run AI analysis

```bash
curl -X POST http://localhost:8000/leads/1/analyze
```

---

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use an in-memory SQLite database and do **not** require PostgreSQL,
OpenAI, or Playwright.

---

## Phase 2 (roadmap)

- Alembic migrations instead of `create_all`.
- Scheduled / batch crawling with politeness & robots.txt respect.
- Dedicated parsing per source (directories, trade sites, LinkedIn, etc.).
- Lead scoring dashboard (frontend).
- Export to CRM / CSV.
- Caching & deduplication improvements.

---

## License

MIT
