"""Assemble a model-free portable directory; exclude development data."""
import importlib.metadata
import json
import shutil
import subprocess
import sys
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


def notices(target):
    inventory = []
    for distribution in importlib.metadata.distributions():
        name, version = distribution.metadata['Name'], distribution.version
        inventory.append({'name': name, 'version': version,
            'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License', ''),
            'url': distribution.metadata.get('Home-page', '')})
        for item in distribution.files or []:
            if '.dist-info/' not in str(item).replace('\\', '/'):
                continue
            if not any(part.lower().startswith(('license', 'notice', 'copying')) for part in item.parts):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file():
                # Keep nested names distinct, e.g. dependency and bundled-library notices.
                parts = item.parts[1:]
                destination = target / 'python' / f'{name}-{version}' / Path(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    (target / 'python-packages.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    python_home = Path(sys.base_prefix)
    if (python_home / 'LICENSE.txt').is_file():
        shutil.copy2(python_home / 'LICENSE.txt', target / 'PYTHON-LICENSE.txt')
    cargo = shutil.which('cargo')
    if cargo:
        metadata = json.loads(subprocess.check_output([cargo, 'metadata', '--locked', '--format-version', '1',
            '--manifest-path', str(ROOT / 'frontend/src-tauri/Cargo.toml')], text=True, encoding='utf-8'))
        rust = []
        for package in metadata['packages']:
            rust.append({key: package.get(key) for key in ('name', 'version', 'license', 'repository')})
            folder = Path(package['manifest_path']).parent
            for item in folder.iterdir():
                if item.is_file() and item.name.lower().startswith(('license', 'notice', 'copying')):
                    destination = target / 'rust' / f"{package['name']}-{package['version']}" / item.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)
        (target / 'rust-packages.json').write_text(json.dumps(rust, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copytree(ROOT / 'packaging/model-notices', target / 'models')
    shutil.copy2(ROOT / 'frontend/node_modules/vue/LICENSE', target / 'VUE-LICENSE.txt')
    shutil.copy2(ROOT / 'frontend/node_modules/@tauri-apps/api/LICENSE-APACHE-2.0', target / 'TAURI-API-LICENSE-APACHE.txt')
    shutil.copy2(ROOT / 'frontend/node_modules/@tauri-apps/api/LICENSE-MIT', target / 'TAURI-API-LICENSE-MIT.txt')


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
    licenses = destination / 'licenses'
    licenses.mkdir()
    notices(licenses)
    print(f'Portable directory: {destination}')


if __name__ == '__main__':
    main()
