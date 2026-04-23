# SmartFlight - Intelligent Flight-Discovery Agent

> An intelligent flight discovery platform developed as part of the NUS CS5260 course.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- (Optional) Docker / Dev Containers

### Development

**Option 1: DevContainer (recommended)**

1. Open in VS Code/Cursor
2. "Reopen in Container"
3. In terminal:
   - Backend: `cd backend && python -m uvicorn smartflight.main:app --reload --host 0.0.0.0 --port 8000`
   - Frontend: `cd frontend && npm run dev`
4. Open http://localhost:5173

If an existing container reports a missing Python package such as `ModuleNotFoundError: No module named 'mcp'`, rerun the setup script from the workspace root:

```bash
bash .devcontainer/post-create.sh
```

Alternatively, rebuild the container so VS Code runs the script automatically.

**Option 2: Local**

```bash
# Backend
cd backend
cp .env.example .env
pip install -r requirements.txt
pip install -e ../flights-search
pip install -e .
python -m uvicorn smartflight.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Environment Variables

Backend-only secrets should stay in the backend runtime environment.

- `backend/.env.example` documents the expected variables.
- `OPENAI_API_KEY` must be set for the backend if you want OpenAI-backed extraction enabled.
- Do not put `OPENAI_API_KEY` in the frontend. Frontend `VITE_*` variables are exposed to the browser.

Example Docker Compose pattern for the backend service:

```yaml
services:
  backend:
    build: ./backend
    env_file:
      - ./backend/.env
    environment:
      OPENAI_API_KEY: ${OPENAI_API_KEY}
```

In production, inject `OPENAI_API_KEY` from the server or deployment platform's secret store at container runtime instead of baking it into the image.

### Tests

```bash
cd backend
pytest
```

## Project Structure

```
├── backend/          # FastAPI (src layout)
│   ├── src/smartflight/
│   │   ├── main.py
│   │   ├── agent/    # LangGraph AI agent
│   │   ├── routers/  # API endpoints
│   │   └── services/ # Business logic & API integrations
│   ├── tests/
│   └── pyproject.toml
├── frontend/         # React + Vite
│   └── src/
└── .devcontainer/
```
