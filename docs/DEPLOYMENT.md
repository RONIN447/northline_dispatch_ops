# Development and deployment

## Local development

Use Python 3.9+ and Node.js 18+.

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

## Render Blueprint

The root `render.yaml` defines one Django web service and one static site. Push the project to GitHub, create a Render Blueprint from that repository, and review the two services and their generated URLs before applying it.

After Render creates the services, set the following values using the actual service URLs:

### Backend web service

- `SECRET_KEY`: use a generated private value.
- `DEBUG`: `False`.
- `ALLOWED_HOSTS`: include the backend's `onrender.com` hostname.
- `FRONTEND_URL`: the frontend's complete `https://` URL.
- `CORS_ALLOWED_ORIGINS`: the frontend's complete `https://` origin. For multiple origins, separate them with commas.

### Frontend static site

Set `VITE_API_BASE_URL` to the backend's complete `https://` URL, then trigger a new frontend deploy because Vite reads this value at build time.

The backend service runs from the `backend` root, starts with `gunicorn wsgi:application`, and uses `/api/health/` for health checks. The frontend service builds with `npm install` and `npm run build`, and publishes `dist`.

## Other hosting providers

For a different frontend host, set its URL in the backend's `FRONTEND_URL` and `CORS_ALLOWED_ORIGINS`. Set the backend URL in `VITE_API_BASE_URL` and rebuild the frontend. Do not commit production secrets or `.env` files.
