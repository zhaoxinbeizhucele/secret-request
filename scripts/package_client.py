"""Distribute the complete skill, optional notifier and source; no credentials."""
from pathlib import Path
import zipfile
from build_skill import build

root = Path(__file__).resolve().parents[1]
build(root)
output = root/'artifacts'
output.mkdir(exist_ok=True)
with zipfile.ZipFile(output/'secret-request-client.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
    for file in (root/'skills/secret-request').rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts:
            archive.write(file, str(file.relative_to(root/'skills')))
print('Client archive ready; configuration excluded.')
