from fastapi.testclient import TestClient

from backend.desktop import ORIGIN, create_desktop_app


TOKEN = 'a' * 64
HEADERS = {'X-PaperReader-Token': TOKEN}


def test_desktop_session_and_cors(tmp_path):
    stopped = []
    app = create_desktop_app(tmp_path, TOKEN, lambda: stopped.append(True))
    with TestClient(app) as client:
        assert client.get('/api/desktop/health').status_code == 401
        assert client.get('/api/desktop/health?desktop_token=' + TOKEN).status_code == 401
        assert client.get('/api/papers').status_code == 401
        assert client.get('/api/desktop/health', headers=HEADERS).json()['status'] == 'ready'
        assert client.get('/api/papers', headers=HEADERS).json() == []
        response = client.options('/api/papers', headers={'Origin': ORIGIN,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'x-paperreader-token,content-type'})
        assert response.status_code == 200
        assert response.headers['access-control-allow-origin'] == ORIGIN
        assert client.options('/api/bookmarks/bookmark', headers={'Origin': ORIGIN,
            'Access-Control-Request-Method': 'PATCH',
            'Access-Control-Request-Headers': 'x-paperreader-token,content-type'}).status_code == 200
        assert client.options('/api/papers', headers={'Origin': 'https://example.com',
            'Access-Control-Request-Method': 'POST'}).status_code == 400
        assert client.post('/api/desktop/shutdown').status_code == 401
        assert stopped == []
        assert client.post('/api/desktop/shutdown', headers=HEADERS).status_code == 202
        assert stopped == [True]


def test_resource_credentials_cannot_access_other_routes(tmp_path):
    app = create_desktop_app(tmp_path, TOKEN, lambda: None)
    with TestClient(app) as client:
        paper = 'b' * 64
        # A valid image credential gets through auth; a missing paper gives 404.
        assert client.get(f'/api/papers/{paper}/pages/1.png?desktop_token={TOKEN}').status_code == 404
        assert client.get(f'/api/papers/{paper}/pages/1.png?desktop_token=wrong').status_code == 401
        assert client.delete(f'/api/papers/{paper}?desktop_token={TOKEN}').status_code == 401


def test_portable_configuration_is_separate_from_development(tmp_path):
    app = create_desktop_app(tmp_path, TOKEN, lambda: None)
    with TestClient(app) as client:
        settings = client.get('/api/llm/settings', headers=HEADERS).json()
        assert not settings['api_key_configured']
        assert app.state.llm_settings.path == tmp_path / 'config' / '.env'
        assert app.state.library.root == tmp_path / 'library'


def test_reference_setting_is_strict_persistent_and_applied_to_worker(tmp_path):
    app = create_desktop_app(tmp_path, TOKEN, lambda: None)
    with TestClient(app) as client:
        initial = client.get('/api/llm/settings', headers=HEADERS).json()
        assert initial['translate_references'] is False
        payload = {key: initial[key] for key in ('base_url', 'model', 'revision')}
        payload.update(base_url='https://example.com/v1', model='test-model')
        assert client.put('/api/llm/settings', headers=HEADERS,
                          json={**payload, 'translate_references': 'false'}).status_code == 422
        response = client.put('/api/llm/settings', headers=HEADERS,
                              json={**payload, 'translate_references': True})
        assert response.status_code == 200
        assert response.json()['translate_references'] is True
        assert app.state.library.translations.translate_references is True
        assert client.get('/api/llm/settings', headers=HEADERS).json()['translate_references'] is True
