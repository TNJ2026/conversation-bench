"""Freeze and stage the opt-in, recovery-only native DSH plugin."""
import hashlib
import json
from pathlib import Path

SOURCE = Path(__file__).parent/'plugins'/'current-history'
FILES = ('package.json','index.cjs','cordis.patch.yml')
TOOLS = ('current_history_search','current_history_read')


def hashes(folder):
    result = {}
    for name in FILES:
        file = folder/name
        if file.is_symlink() or not file.is_file():
            raise ValueError('History plugin requires regular files: '+name)
        result[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def freeze(root):
    source_hashes = hashes(SOURCE)
    target = root/'history-plugin'
    target.mkdir()
    for name in FILES:
        (target/name).write_bytes((SOURCE/name).read_bytes())
    if hashes(target) != source_hashes:
        raise ValueError('History plugin changed while freezing.')
    return {'name':'conversation-bench-current-history',
            'version':json.loads((target/'package.json').read_text())['version'],
            'snapshot':str(target.resolve()), 'sha256':source_hashes,
            'tools':list(TOOLS), 'activation':'recovery-only'}


def stage(home, metadata):
    source = Path(metadata['snapshot'])
    if source.is_symlink() or hashes(source) != metadata['sha256']:
        raise ValueError('Frozen history plugin changed; refusing to run.')
    target = home/'bench-current-history'
    if target.is_symlink():
        raise ValueError('History plugin directory must not be a symlink.')
    target.mkdir(exist_ok=True)
    for name in FILES:
        file = target/name
        if file.is_symlink():
            raise ValueError('History plugin files must not be symlinks.')
        if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest() != metadata['sha256'][name]:
            raise ValueError('Staged history plugin changed; refusing to overwrite it.')
        if not file.exists():
            file.write_bytes((source/name).read_bytes())
    if hashes(target) != metadata['sha256']:
        raise ValueError('Staged history plugin hash mismatch.')
    return target/'cordis.patch.yml'


def evidence(metadata, events):
    calls = [e for e in events if e.get('type') == 'tool/call' and e.get('data',{}).get('name') in TOOLS]
    return {'name':metadata['name'], 'version':metadata['version'], 'sha256':metadata['sha256'],
            'registered':True, 'activation':metadata['activation'],
            'calls':[{'seq':e['seq'],'name':e['data']['name']} for e in calls]}
