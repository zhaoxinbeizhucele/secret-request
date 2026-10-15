"""Distribute explicit skill files; unrelated local files are never included."""
from pathlib import Path
import zipfile
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from .build_skill import build
    from .distribution import client_files
except ImportError:
    from build_skill import build
    from distribution import client_files

def package(root, output):
    bundle = root/'skills/secret-request'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in client_files(bundle):
            archive.write(path, str(path.relative_to(root/'skills')))


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    build(root)
    (root/'artifacts').mkdir(exist_ok=True)
    package(root, root/'artifacts/secret-request-client.zip')
    print('Client archive ready; only explicit distribution files included.')
