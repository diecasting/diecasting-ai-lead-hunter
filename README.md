# Diecasting AI Lead Hunter

A B2B **AI customer-search system for the metal die-casting industry**.

It discovers die-casting manufacturers / OEMs from the web, stores them as
**company leads** in PostgreSQL, and uses the **OpenAI API** to score each lead's
fit and surface buying-intent signals — so a sales team can focus on the
companies most likely to need die-casting services.

> **Status:** Phase 2.2 — production lead-generation backend (website crawler &
> lead extraction). No frontend is included.

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

## Features

### Phase 1 (backend MVP)
1. **Project structure** — clean, package-based FastAPI layout.
2. **Company Lead table** — `company_leads` with firmographics + AI-enrichment columns.
3. **AI analysis module** — `app/ai/analyzer.py` scores relevance and surfaces signals.
4. **REST API** — CRUD for leads plus `POST /leads/ingest` and `POST /leads/{id}/analyze`.

### Phase 2.1 — Google SERP search
- `app/search/` — Playwright Google SERP search, tolerant HTML parser, directory
  filters (drops Alibaba / Made-in-China / IndiaMart / Thomasnet / Wikipedia /
  directories) and optional manufacturer-only keep, persists `search_results`,
  creates `company_leads` + `crawl_tasks`.

### Phase 2.2 — Website crawler & lead extraction (this release)
- `app/crawler/website_crawler.py` — crawls `/`, `/about`, `/about-us`, `/company`,
  `/products`, `/industries`, `/solutions`, `/contact`, `/contact-us`,
  `/request-quote`, `/rfq`; respects `robots.txt`, discovers `sitemap.xml` and
  internal links, applies per-page **timeout + retry**.
- `app/crawler/page_discovery.py` — scans HTML links and classifies them into
  Contact / Product / Company pages (`discovered_pages`).
- `app/crawler/email_extractor.py` — extracts `xxx@company.com`, drops
  `example.com` / `test.com` / `noreply@` / `support@` / `privacy@`, and
  **prioritises** sales / export / business / inquiry / contact / info mailboxes.
- `CompanyLead` extended with `contact_emails` (JSON), `crawl_status`
  (pending/running/success/failed), `pages_crawled`, `website_content`,
  `crawl_time`.

### Phase 2.3 — AI lead scoring
- `app/ai/scoring.py` — deterministic `casting_need_score` (Automotive +30, EV +30,
  Aluminum +25, Magnesium +25, CNC +15, OEM +15, capped 100) and
  `sales_priority` (HIGH ≥ 80 / MEDIUM ≥ 50 / LOW).

### Phase 2.4 — PostgreSQL + Alembic
- Production PostgreSQL; schema managed by **Alembic** migrations
  (`migrations/`) creating `company_leads`, `search_results`, `crawl_tasks`,
  `ai_analysis`.

### Phase 2.6 — CRM export
- `GET /export/csv` — generates `sales_leads.csv` (company, country, website,
  industry, products, email, score, reason, priority) and streams it.

---

## Project structure

```
diecasting-ai-lead-hunter/
├── app/
│   ├── main.py              # FastAPI app, lifespan, health, CORS
│   ├── config.py            # pydantic-settings (env / .env)
│   ├── database.py          # engine, SessionLocal, Base, get_db
│   ├── pipeline.py          # end-to-end daily pipeline (search→crawl→score)
│   ├── scheduler.py         # APScheduler daily job (06:00 UTC)
│   ├── models/              # lead, search_result, crawl_task, ai_analysis
│   ├── schemas/             # lead, search, crawl (Pydantic)
│   ├── crud/                # leads, search_results, crawl_tasks, ai_analysis
│   ├── routers/             # leads (CRUD + ingest + analyze)
│   ├── api/                 # crawl, search, export routers
│   ├── search/              # SERP provider + filters + keywords + service
│   ├── crawler/             # website_crawler, page_discovery, email_extractor, runner
│   └── ai/                  # analyzer, scoring
├── migrations/              # Alembic env + versions
├── scripts/init_db.py       # runs `alembic upgrade head` (fallback create_all)
├── tests/                   # page_discovery, email_extraction, crawler, export, migration, main
├── Dockerfile / docker-compose.yml / entrypoint.sh
├── requirements.txt / requirements-dev.txt / pyproject.toml / .env.example
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
# Production: apply Alembic migrations
alembic upgrade head
# or, convenience wrapper that runs the migrations (falls back to create_all)
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
runs `alembic upgrade head` before starting the server.

---

## Environment variables

| Variable              | Default                              | Description                              |
|-----------------------|--------------------------------------|------------------------------------------|
| `APP_NAME`            | `diecasting-ai-lead-hunter`          | App title                               |
| `DEBUG`               | `false`                             | FastAPI debug mode                      |
| `DATABASE_URL`        | *(built from parts)*                | Full SQLAlchemy DB URL (overrides parts)|
| `POSTGRES_*`          | `localhost:5432/postgres/leadhunter`| Individual DB connection parts          |
| `OPENAI_API_KEY`      | —                                   | Optional; scoring works without it      |
| `OPENAI_MODEL`        | `gpt-4o-mini`                       | Chat model used for analysis summary    |
| `CRAWLER_HEADLESS`    | `true`                              | Run Chromium headless                  |
| `CRAWLER_MAX_PAGES`   | `50`                                | Crawl budget per site                   |
| `CRAWLER_MAX_RETRIES` | `3`                                | Per-page retry attempts                 |
| `SCHEDULER_ENABLED`   | `false`                             | Enable the daily 06:00 UTC pipeline     |
| `KEYWORDS_FILE`       | `data/keywords.txt`                 | Keyword library for the scheduler       |
| `EXPORT_DIR`          | `data/exports`                      | Where `sales_leads.csv` is written      |

---

## API reference

Base URL: `http://localhost:8000`

| Method | Path                     | Description                                      |
|--------|--------------------------|--------------------------------------------------|
| GET    | `/health`                | Health check                                     |
| GET    | `/leads`                 | List leads (`?priority=HIGH` to filter)          |
| POST   | `/leads`                 | Create a lead                                    |
| GET    | `/leads/{id}`            | Get a lead by id                                 |
| PATCH  | `/leads/{id}`            | Partially update a lead                          |
| DELETE | `/leads/{id}`            | Delete a lead                                    |
| POST   | `/leads/ingest`          | Run SERP search and persist new leads            |
| POST   | `/leads/{id}/analyze`    | Run AI scoring / enrichment on a lead            |
| POST   | `/search`                | Run a Google SERP search (`{keyword, limit}`)    |
| GET    | `/search/results`        | List stored `search_results`                     |
| POST   | `/crawl/{lead_id}`       | Start crawling a lead's website                  |
| GET    | `/crawl/status/{lead_id}`| Crawl status / result summary                    |
| GET    | `/export/csv`            | Download `sales_leads.csv`                       |

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

## Roadmap

- [x] **Phase 2.1** — Google SERP search + filtering + `search_results`.
- [x] **Phase 2.2** — Website crawler, page discovery, email extraction, CRM CSV export.
- [x] **Phase 2.3** — Deterministic `casting_need_score` / `sales_priority`.
- [x] **Phase 2.4** — PostgreSQL + Alembic migrations (`company_leads`,
      `search_results`, `crawl_tasks`, `ai_analysis`).
- [x] **Phase 2.5** — APScheduler daily pipeline (search → crawl → score).
- [x] **Phase 2.6** — CRM CSV export.
- [x] **Phase 2.7** — pytest suite (page discovery, email extraction, crawler,
      export, migration, API).
- [ ] Lead scoring dashboard (frontend).
- [ ] Dedicated parsing per source (directories, trade sites, LinkedIn, etc.).
- [ ] Caching & deduplication improvements.

---

## License

MIT
