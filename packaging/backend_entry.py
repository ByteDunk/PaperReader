"""PyInstaller entry point. Configure paths before importing the application."""
import multiprocessing


if __name__ == '__main__':
    multiprocessing.freeze_support()
    import argparse
    import sys
    from pathlib import Path

    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--models-dir', required=True)
    args = parser.parse_args()
    from backend.model_download import prepare_models
    if prepare_models(args.models_dir):
        from backend.desktop import serve
        serve(args.data_dir, args.models_dir)
