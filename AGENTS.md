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

## AI-Generated Explanations (DeepSeek LLM)
The analyzer prompts DeepSeek to produce two additional evidence-based outputs:

### gottman_explanations
For each of the Four Horsemen (Criticism, Contempt, Defensiveness, Stonewalling):
- The AI generates 1-2 evidence-based sentences explaining what the specific scores mean
  for this particular relationship.
- Must reference concrete patterns or examples from the conversation as evidence.
- Must use Gottman's research framework (e.g., Criticism attacks character not behavior;
  Contempt includes sarcasm, mockery, hostile humor; Contempt is the #1 predictor of divorce).
- If BOTH people score 0 on a horseman, that key is omitted from the response entirely.

### circumplex_summary
- 2-3 sentences interpreting the interpersonal circumplex (radar chart) patterns.
- Discusses who leads on dominance/warmth/hostility dimensions.
- Describes whether the dynamic is complementary, conflicted, or balanced.
- References specific axis values as evidence.

These explanations are rendered in the frontend directly from the API response:
- `data.gottman.explanations[key]` → displayed below each horseman bar
- `data.circumplex_summary` → displayed below the radar chart legend

Do NOT use static/score-based template text in the frontend — explanations must come from the AI.

## Running
```bash
cd /Users/yingying/Desktop/Gasoff && python -m backend.main
```
