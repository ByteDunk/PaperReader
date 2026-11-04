# Build on Windows x64 with backend/.venv. Models and user data stay outside the executable.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
datas, binaries, hidden = [], [], []

def include_mineru(name):
    return not any(name == prefix or name.startswith(prefix + '.') for prefix in (
        'mineru.cli', 'mineru.kit', 'mineru.integrations', 'mineru.doclib', 'mineru.parser.api_server'))

hidden += collect_submodules('mineru', filter=include_mineru)
hidden += collect_submodules('docvortex')
hidden += collect_submodules('fastembed')
hidden += ['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
           'uvicorn.lifespan.on', 'sqlite_vec', 'pypdfium2_raw']
for package in ('mineru', 'docvortex', 'fastembed', 'tokenizers', 'onnxruntime', 'sqlite_vec',
                'pypdfium2', 'pypdfium2_raw', 'jieba'):
    datas += collect_data_files(package, excludes=['datasets'] if package == 'onnxruntime' else [])
    binaries += collect_dynamic_libs(package)
for package in ('mineru', 'docvortex', 'fastembed', 'onnxruntime', 'tokenizers', 'modelscope',
                'huggingface-hub', 'pypdfium2', 'sqlite-vec'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'packaging/backend_entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['torch', 'torchvision', 'transformers', 'gradio', 'gradio_client',
                       'matplotlib', 'tkinter', 'pytest', 'IPython', 'notebook', 'jupyter'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='paperreader-backend',
          debug=False, strip=False, upx=False, console=True,
          icon=str(root / 'frontend/src-tauri/icons/icon.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='paperreader-backend')
