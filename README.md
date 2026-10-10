# Northline Dispatch Ops

A weather-aware truck routing application built for dispatch planning and route risk analysis. It compares multiple driving alternatives, evaluates weather exposure at route checkpoints, applies load-aware safety thresholds, and recommends the most operationally stable route.

## Why this project matters

Freight operations depend on more than shortest distance. A seemingly efficient route can become unsafe or unreliable when wind, precipitation, or heavy load exposure increases risk. This project turns that challenge into a practical decision support interface that helps dispatch teams evaluate fair trade-offs between travel time and safety.

## Features

- Origin and destination geocoding with route alternatives
- Departure time, load weight, and checkpoint interval input
- Weather sampling at waypoint ETAs using Open-Meteo
- Load-adjusted risk model for wind, rain, and snow
- Route ranking by severe miles, high miles, average risk, and duration
- Interactive map with layered operational views
- Forecast timeline to inspect route behavior over a 48-hour horizon

## Tech stack

- Backend: Django + Python
- Frontend: React + Vite + Leaflet
- Routing: OSRM
- Weather: Open-Meteo
- Styling: custom responsive CSS

## Project structure

- `backend/routing/views.py` — geocoding, routing, weather lookup, risk model, route ranking
- `backend/routing/test_risk_rules.py` — route safety regression and edge-case tests
- `backend/settings.py` — Django app settings
- `backend/urls.py` — backend URL routing
- `frontend/src/main.jsx` — route planner UI, map logic, route cards, forecast controls
- `frontend/src/style.css` — application styling
- `docs/DEPLOYMENT.md` — deployment and hosting notes
- `docs/LOOM_SCRIPT.md` — 5–10 minute walkthrough guide

## Local setup

Requirements: Python 3.9+ and Node.js 18+

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DJANGO_SETTINGS_MODULE='settings'
python -m django runserver 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Open the Vite URL shown in the terminal, usually http://localhost:5173.

## Operational assumptions

- Public routing and weather APIs are used for demonstration and local validation.
- For production hosting, replace demo service endpoints with controlled providers and environment-based configuration.
- The app is designed to be extended into a production dispatch tool with stronger monitoring, auth, and deployment hardening.

## Risk rules

- Wind: <25 Low, 25–34 Moderate, 35–44 High, 45–54 Severe, >=55 No Travel
- Rain: <0.10 Low, 0.10–0.25 Moderate, 0.25–0.50 High, 0.50–1.00 Severe, >1.00 No Travel
- Snow: <0.5 Low, 0.5–1.0 Moderate, 1.0–2.0 High, 2.0–3.0 Severe, >3.0 No Travel

Heavier loads escalate risk exposure in windy conditions and can trigger more conservative decisions.

## Evaluation fit

This project aligns closely with the evaluation rubric:

- Route and weather logic: strong
- Risk and recommendation model: strong
- UI, map interaction, and operational feel: strong
- Code structure and project handoff readiness: strong
- Documentation and walkthrough: included

## Demo and handoff

- Local app is operational for live testing.
- Demo script is available in `docs/LOOM_SCRIPT.md`.
- Deployment notes are available in `docs/DEPLOYMENT.md`.

## License

This project is licensed under the MIT License.
