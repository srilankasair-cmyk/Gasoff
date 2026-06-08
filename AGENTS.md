# Gas-off Project Guidelines

## Architecture
- **Backend**: Python Flask, served from `backend/main.py`
- **Frontend (TWA)**: Single HTML page in `frontend/build/web/index.html`
- **API endpoints**:
  - `POST /webhook` — Telegram bot incoming
  - `GET /api/analysis/<id>` — TWA fetches result
  - `GET /twa/*` — Serves TWA SPA
- **No external packages beyond**: flask, httpx, pydantic, python-dotenv

## Key behaviors
- `analyzer.py` falls back to mock data when `DEEPSEEK_API_KEY` is unset
- De-identification strips: @usernames, phone, email, address, date, long numbers
- Analysis results stored in-memory (not persisted); replace with Redis/DB for production
- TWA frontend auto-falls back to demo data if API returns 404

## Running
```bash
cd /Users/yingying/Desktop/Gasoff && python -m backend.main
```
