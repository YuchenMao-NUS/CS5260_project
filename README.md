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
   - Backend: `cd backend && uvicorn smartflight.main:app --reload --host 0.0.0.0 --port 8000`
   - Frontend: `cd frontend && npm run dev`
4. Open http://localhost:5173

**Option 2: Local**

```bash
# Backend
cd backend
pip install -r requirements.txt
pip install -e .
uvicorn smartflight.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

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
