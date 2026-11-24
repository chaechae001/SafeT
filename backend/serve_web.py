"""Serve the Safe-T browser UI and API on one HTTP port."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles

from main import app as api, lifespan

frontend = Path(__file__).resolve().parents[1] / 'frontend'
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get('/')
def home():
    # Elice strips the public prefix before proxying the request.
    return RedirectResponse('pages/login.html')


@app.get('/health')
def health():
    return {'status': 'ok', 'commit': os.getenv('SAFET_REVIEW_COMMIT')}


@app.get('/js/config.js')
def browser_configuration():
    return Response(
        'window.SAFET_API_BASE = new URL("../api", document.currentScript.src).pathname;\n',
        media_type='application/javascript',
        headers={'Cache-Control': 'no-cache'},
    )


app.mount('/api', api)
for directory in ('css', 'js', 'pages', 'public'):
    app.mount('/' + directory, StaticFiles(directory=frontend / directory))
