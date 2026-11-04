"""Pinned runtime assets; shared by preflight, ModelScope downloads and packaging."""
from pathlib import Path

from .resources import read_json, write_json


MODEL_GROUPS = (
    {
        'id': 'mineru',
        'title': '文档解析模型',
        'folder': 'MinerU-4_models_onnx',
        'repository': 'OpenDataLab/MinerU-4_models_onnx',
        'revision': 'e916a9d96d645d005364abd7db8ffd4b7353cf4f',
        'files': {
            'Layout/PP-DocLayoutV2/inference.onnx': (213963712, 'cd540dc296ff3115fe78efa65b68501e6a8dc74b198acc9834a725ffaa095aac'),
            'Layout/PP-DocLayoutV2/inference.yml': (1482, '93100e0fb2cd76b9d246a853deea85e191d8333b2cfca7be76e82e4c4ebfa819'),
            'MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.onnx': (591263297, '20a32595c2b30282dcd069e6295e9fad96115697beb66acb9b681b814006d193'),
            'MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M_inference.yml': (2244564, '87b5f3d7f2b2fe553627d77b37f496608ca150ebd0ef62d362591edca47b5538'),
            'OCR/paddleocr/ch_PP-OCRv6_tiny_det_infer.onnx': (1780590, '193bab7a04fca699a6c82e6abb5b81bdb28177f0abd4062552b04908dafb19f8'),
            'OCR/paddleocr/ch_PP-OCRv6_small_rec_infer.onnx': (21159378, '5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634'),
            'OCR/paddleocr/seal_PP-OCRv4_det_infer.onnx': (4769171, '3e190df84542c2756975febe8f73603b587a23c7f7badfdd3fc8a986540d5bc0'),
        },
    },
    {
        'id': 'embedding',
        'title': '语义检索模型',
        'folder': 'Qwen3-Embedding-0.6B-INT8',
        'repository': 'Qdrant/Qwen3-Embedding-0.6B-onnx',
        'revision': 'd6e3f582bf20423688686548ba2a030265c06b07',
        'files': {
            'onnx/model_quantized.onnx': (1120604114, 'b39d0623bfc7d2dfc2dcc0d32152c5c5b8d61e9e74679e8222dcce5cf32486b9'),
            'config.json': (747, 'da2b52e46d1469b9f6ff3a45e2bec36b2bb667de5ea9dd5a076e8bfe3b30cc05'),
            'tokenizer.json': (11423705, 'def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a'),
            'tokenizer_config.json': (5402, '1c45aaa97b2bec1d2e1ab0df53e1b2ed2f9568b871b25ca56095c0b83a5d4e93'),
            'special_tokens_map.json': (613, '76862e765266b85aa9459767e33cbaf13970f327a0e88d1c65846c2ddd3a1ecd'),
        },
    },
)


def missing_model_files(directory, groups=MODEL_GROUPS):
    directory = Path(directory)
    return [(group, name) for group in groups for name, (size, _) in group['files'].items()
            if not (path := directory / group['folder'] / name).is_file() or path.stat().st_size != size]


def ensure_embedding_manifest(directory):
    """Generate local metadata offline; weights always come from the pinned catalog."""
    group = MODEL_GROUPS[1]
    path = Path(directory) / group['folder'] / 'manifest.json'
    expected = {'repository': group['repository'], 'revision': group['revision'], 'precision': 'int8',
                'files': {name: {'size': size, 'sha256': digest} for name, (size, digest) in group['files'].items()}}
    try:
        if read_json(path) == expected:
            return
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, expected)


def validate_models(directory):
    missing = [f"{group['folder']}/{name}" for group, name in missing_model_files(directory)]
    if missing:
        raise RuntimeError('本地模型缺失或不完整，需要下载：' + ', '.join(missing))
    ensure_embedding_manifest(directory)
