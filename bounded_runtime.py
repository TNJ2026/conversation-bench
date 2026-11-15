"""Shared installed-DSH runtime helpers for bounded delivery."""
import hashlib
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parent
DSH_BIN = '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def runtime_fingerprint(config):
    binary = Path(config['dsh_bin']).resolve()
    resources = binary.parents[3]
    metadata = resources / 'runtime/primary-runtime/runtime.json'
    archive = resources / 'app.asar'
    if not metadata.is_file() or not archive.is_file():
        raise ValueError('Bounded delivery supports the installed macOS DSH runtime only.')
    version = subprocess.run([str(binary), '--version'], capture_output=True, text=True,
                             check=True, timeout=20).stdout.strip()
    if version != config['app_version']:
        raise ValueError('Installed DSH version differs from requested version.')
    return dict(version=version, launcher_sha256=sha(binary), runtime_metadata_sha256=sha(metadata),
                app_archive_sha256=sha(archive))


def new_workspace(prefix):
    workspace = ROOT.parent / 'conversation-bench-workspaces' / (prefix + uuid.uuid4().hex)
    workspace.mkdir(parents=True)
    return workspace
