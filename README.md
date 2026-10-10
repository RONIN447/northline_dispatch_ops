# Northline Dispatch Ops

Northline Dispatch Ops compares truck routes using forecast weather, cargo weight, and travel time. Enter a start, destination, departure time, and load weight to view route alternatives, checkpoint conditions, and a safety-first recommendation.

## Features

- Geocodes origin and destination with Open-Meteo Geocoding.
- Requests up to three driving routes from OSRM.
- Samples wind, rain, and snow at 10, 25, or 50 mile checkpoints using estimated checkpoint arrival times.
- Applies the assessment's weather and load thresholds, then ranks routes by severe miles, high-risk miles, distance-weighted average risk, and duration.
- Shows route alternatives, checkpoint ETAs and conditions, a risk overlay, and a 0–48 hour departure forecast control.

## Stack

- Frontend: React, Vite, Leaflet, and React Leaflet
- Backend: Django and Python
- Routing: OSRM public demo service
- Geocoding and weather: Open-Meteo

## Run locally

Requirements: Python 3.9 or newer and Node.js 18 or newer.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DJANGO_SETTINGS_MODULE='settings'
$env:DEBUG='True'
python -m django runserver 8000
```

### Frontend

In a second terminal:

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL='http://127.0.0.1:8000'
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`. The backend permits that local origin for development. `.env.example` lists the supported environment variables.

## Risk rules

| Condition | Low | Moderate | High | Severe | No Travel |
| --- | --- | --- | --- | --- | --- |
| Wind (mph) | <25 | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–<0.25 | 0.25–<0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–<1.0 | 1.0–<2.0 | 2.0–3.0 | >3.0 |

Load adjustments:

- Wind at or above 55 mph is No Travel for any load.
- Wind from 45 to under 55 mph is No Travel above 30,000 lb.
- Wind from 35 to under 45 mph is at least Severe above 40,000 lb.

## Deploy on Render

The repository includes a Render Blueprint in `render.yaml` for a Django web service and a static frontend. In Render, create a Blueprint instance from the GitHub repository and review the generated services before applying it. Set the frontend's deployed URL as `FRONTEND_URL` and `CORS_ALLOWED_ORIGINS` on the backend, and set the backend URL as `VITE_API_BASE_URL` for the frontend build. Keep `SECRET_KEY` private and set `DEBUG=False` in production.

The backend start command is `gunicorn wsgi:application` from the `backend` directory. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for details.

## Limitations

- Public OSRM and Open-Meteo services are demonstration providers with availability and rate limits outside this project's control.
- Weather is hourly forecast data sampled at the nearest available hour. If a checkpoint falls outside the available forecast, the app reports the forecast as unavailable rather than treating it as safe.
- Route alternatives depend on what the routing provider returns; fewer than three may be available for some trips.
- The recommendation is decision support and should be checked against current road and carrier safety guidance before dispatch.

## Project layout

- `backend/routing/views.py` — geocoding, route retrieval, weather sampling, risk scoring, and ranking
- `backend/routing/test_risk_rules.py` — focused risk and input regression tests
- `frontend/src/main.jsx` — route planner, forecast control, route cards, and map
- `frontend/src/style.css` — responsive interface styling
- `docs/DEPLOYMENT.md` — local and hosted deployment notes
- `docs/LOOM_SCRIPT.md` — walkthrough outline

## License

MIT. See [LICENSE](LICENSE).
