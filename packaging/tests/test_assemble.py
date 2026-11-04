import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def assemble():
    spec = importlib.util.spec_from_file_location('portable_assemble', Path(__file__).parents[1] / 'assemble.py')
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    return assemble


def test_release_directory_excludes_models(tmp_path, monkeypatch, assemble):
    executable = tmp_path / '.build/tauri/x86_64-pc-windows-msvc/release/paperreader.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'test desktop fixture')
    backend = tmp_path / '.build/backend-dist/paperreader-backend/paperreader-backend.exe'
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b'test backend fixture')
    monkeypatch.setattr(assemble, 'ROOT', tmp_path)
    monkeypatch.setattr(assemble, 'RELEASE', tmp_path / 'release')
    monkeypatch.setattr(assemble, 'notices', lambda _: None)
    assemble.main()
    destination = tmp_path / 'release' / assemble.NAME
    assert not (destination / '使用说明.txt').exists()
    assert not (destination / 'models').exists()
    assert list(assemble.RELEASE.iterdir()) == [destination]
