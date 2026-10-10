# Deployment Guide

This project is ready to be run locally and staged for deployment.

## Local development

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DJANGO_SETTINGS_MODULE='settings'
python -m django runserver 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

## Production hosting options

### Render (recommended for full-stack Django + React)

1. Create a new Web Service for the backend folder.
2. Use Python 3.9+ and install from `backend/requirements.txt`.
3. Set environment variables:
   - `DJANGO_SETTINGS_MODULE=settings`
   - `SECRET_KEY`
   - `DEBUG=False`
   - `ALLOWED_HOSTS=*`
4. Use the built-in start command:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn settings.wsgi:application
```

5. Create a static site for the frontend and deploy `frontend/dist` after running:

```bash
npm install
npm run build
```

### Vercel + Render split

- Frontend: deploy the `frontend` app to Vercel.
- Backend: deploy the `backend` app to Render or Railway.
- Update the frontend fetch target to the deployed backend URL.

## Production hardening checklist

- Replace demo OSRM and Open-Meteo usage with production-grade providers.
- Move `SECRET_KEY` into environment variables.
- Set `DEBUG=False`.
- Add CORS and CSRF protections.
- Use a real database instead of the default dev settings.
- Add health checks and monitoring.
