# Nen Reference Finder — deployable

Internal tool: paste a project brief → 4 reference videos to pitch; click one → its script.
Plus a categorized hook library on the main page. Password-protected.

Self-contained: `app.py` + `index.html` + `style.css` + `fonts/` + `data/` (JSON) + `frames/` (JPEGs).
No AI dependencies — just Flask.

## Run locally
```
pip install -r requirements.txt
python app.py            # http://localhost:5000  (login: any username, password = "nen")
```

## Deploy to Render (free, ~10 min)
1. Put this folder in a **GitHub repo** (see commands below).
2. Go to **render.com** → New → **Web Service** → connect the repo.
   Render reads `render.yaml` automatically (Python, `gunicorn app:app`).
3. Under **Environment**, set `APP_PASSWORD` to a password of your choice.
4. Deploy. You get a private `https://<name>.onrender.com` URL — share it + the password.

### Push to GitHub
```
git init && git add . && git commit -m "Nen reference finder"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Login is HTTP Basic auth: any username, the password is whatever `APP_PASSWORD` is set to.
