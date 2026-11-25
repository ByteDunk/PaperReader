"""Assemble a model-free portable directory; exclude development data."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / 'frontend/src-tauri/tauri.conf.json').read_text(encoding='utf-8'))['version']
NAME = f'PaperReader-{VERSION}-win11-x64'
RELEASE = ROOT / 'release'


def clean_generated_directory(path, parent):
    path, parent = path.resolve(), parent.resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError(f'Refusing to replace directory outside {parent}: {path}')
    if path.exists():
        if (path / 'data').exists():
            raise RuntimeError(f'{path} contains application data. Move it before rebuilding this release.')
        shutil.rmtree(path)


def main():
    executable = ROOT / '.build/tauri/x86_64-pc-windows-msvc/release/paperreader.exe'
    backend = ROOT / '.build/backend-dist/paperreader-backend'
    if not executable.is_file() or not (backend / 'paperreader-backend.exe').is_file():
        raise RuntimeError('Build the desktop executable and backend first.')
    RELEASE.mkdir(exist_ok=True)
    destination = RELEASE / NAME
    clean_generated_directory(destination, RELEASE)
    destination.mkdir()
    shutil.copy2(executable, destination / 'PaperReader.exe')
    shutil.copytree(backend, destination / 'backend')
    # App-local VC runtime also covers the Rust host and WebView2 loader.
    for library in ('msvcp140.dll', 'MSVCP140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
        source = backend / '_internal' / library
        if source.is_file():
            shutil.copy2(source, destination / library)
    print(f'Portable directory: {destination}')


if __name__ == '__main__':
    main()
