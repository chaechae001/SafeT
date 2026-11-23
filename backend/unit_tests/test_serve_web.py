import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_web_app_behind_elice_proxy(monkeypatch):
    monkeypatch.setenv('DB_HOST', '127.0.0.1')
    monkeypatch.setenv('DB_NAME', 'safet_test')
    monkeypatch.setenv('DB_USER', 'safet_test')
    monkeypatch.setenv('SAFET_REVIEW_COMMIT', 'example')
    from serve_web import app

    with TestClient(app, root_path='/proxy/8021') as client:
        redirect = client.get('/', follow_redirects=False)
        assert redirect.headers['location'] == 'pages/login.html'
        assert client.get('/pages/login.html').status_code == 200
        config = client.get('/js/config.js')
        assert config.status_code == 200
        assert 'window.SAFET_API_BASE' in config.text
        assert client.get('/health').json()['commit'] == 'example'
        assert '/proxy/8021/api/openapi.json' in client.get('/api/docs').text
        assert '/health/db' in client.get('/api/openapi.json').json()['paths']
