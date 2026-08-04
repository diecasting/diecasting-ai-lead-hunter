# Die Casting Lead Hunter — Admin Dashboard

A lightweight React + TypeScript single-page admin UI for the
`diecasting-ai-lead-hunter` FastAPI backend. It lets you manage leads, generate
outreach emails, review drafts, and inspect lead quality scores through the
existing API — no new backend endpoints required.

## Features

- **Leads** — list with priority filter + free-text search; create / edit /
  delete; view full profile; run *AI Analysis* / *Full Intelligence*; change
  pipeline status; generate outreach email; browse a lead's messages.
- **Outreach Drafts** — review every generated draft (subject, role, body,
  status) and jump to its lead.
- **Quality & Ranking** — leads ranked by the composite `lead_score` (with
  priority filter + min-score), plus the untouched *High Value* shortlist. Score
  bars and priority badges recompute from the API.

## Tech

- Vite + React 18 + TypeScript
- React Router (hash routing, so it works from `file://` or any static host)
- No UI kit — a small hand-rolled CSS theme (dark) to keep the dependency
  surface tiny and the install fast.

## Running locally

### 1. Start the backend (FastAPI on :8000)

From the repo root:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API already allows CORS `*` and the dashboard proxies `/api` →
`http://localhost:8000`, so no extra config is needed.

### 2. Start the dashboard

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 3. Build for production

```bash
npm run build      # outputs to frontend/dist
npm run preview    # serve the built bundle locally
```

To point the build at a different backend, set `VITE_API_BASE` (a full origin,
e.g. `https://api.example.com`) at build time. When unset, requests go to
`/api` and are proxied by Vite (dev) or your static host.

## Project layout

```
frontend/
  index.html
  vite.config.ts        # /api proxy → backend
  tsconfig.json
  package.json
  src/
    main.tsx            # router + entry
    App.tsx             # sidebar shell
    index.css           # theme
    api.ts              # fetch client (mirrors backend routes)
    types.ts            # TS types for leads / messages / ranking
    utils.ts            # score colors, breakdown parse, date format
    components/
      LeadFormModal.tsx # create / edit lead
    pages/
      LeadsPage.tsx     # list + filters + new
      LeadDetailPage.tsx# detail + actions + messages
      DraftsPage.tsx    # draft review
      QualityPage.tsx   # ranking + high-value
```
