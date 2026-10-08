"""Create a local ML handover archive with verified model/data bytes, no environments."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    release = (ROOT / args.release).resolve()
    if not release.is_relative_to(ROOT / 'models/releases'):
        raise ValueError('Release must be inside models/releases')
    metadata = json.loads((release / 'metadata.json').read_text(encoding='utf-8'))
    if (metadata['status'] not in ('experimental', 'frozen')
            or sha(release/'model.tflite') != metadata['sha256']
            or sha(release/'labels.txt') != metadata['labels_sha256']
            or (release/'model.tflite').stat().st_size != metadata['model_bytes']):
        raise ValueError('Unverified release or model hash mismatch')
    selected = json.loads((ROOT/'experiments/reports'/metadata['experiment_id']/'result.json').read_text(encoding='utf-8'))
    if selected['checkpoint_sha256'] != metadata['checkpoint_sha256']:
        raise ValueError('Release does not match the selected checkpoint')
    release_files = json.loads((release/'release-files.json').read_text(encoding='utf-8'))
    for name, expected in release_files.items():
        path = (release/name).resolve()
        if not path.is_relative_to(release) or sha(path) != expected:
            raise ValueError('Release file changed: '+name)
    files = {ROOT/'.gitattributes', ROOT/'.gitignore', ROOT/'data/README.md'}
    current_source = hashlib.sha256()
    for path in sorted((ROOT/'ml/src/recognition').glob('*.py')):
        current_source.update(path.name.encode())
        current_source.update(path.read_bytes())
    if current_source.hexdigest() != selected['identity']['code_snapshot_sha256']:
        raise ValueError('Restore the selected training source before packaging a reproducible workspace')
    for directory in [ROOT/'ml/src', ROOT/'ml/configs', ROOT/'ml/tests', ROOT/'shared', release, ROOT/'scripts']:
        files.update(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for pattern in ['ml/*.toml', 'ml/*.txt', 'ml/*.lock', 'ml/*.ini', 'ml/README.md', 'tests/model-handover-cases.csv']:
        files.update(ROOT.glob(pattern))
    for name in ['model-contract.md', 'ml-handover.md', 'ml-experiments.md', 'ml-expanded-experiments.md', 'ml-gpu-experiments.md', 'ml-gpu-environment.md', 'ml-photo-gaps.md', 'environment.md']:
        path = ROOT/'docs'/name
        if path.exists(): files.add(path)
    files.update(p for p in (ROOT/'experiments/reports').rglob('*') if p.is_file() and not (p.parent.name=='audit' and p.suffix=='.png'))
    files.update((ROOT/'data/manifests').glob('*.csv'))
    # Preserve the actual ImageNet initialization so this campaign can run offline.
    files.update((ROOT/'experiments/checkpoints/keras-cache/models').glob('*.h5'))
    data = ROOT/'data/splits'/metadata['data_version']
    dataset = json.loads((data/'dataset.json').read_text(encoding='utf-8'))
    if sha(data/'dataset.json') != selected['identity']['data_metadata_sha256']:
        raise ValueError('Dataset metadata changed since training')
    if sha(data/dataset['source_snapshot']['file']) != dataset['source_snapshot']['sha256']:
        raise ValueError('Frozen audited source changed')
    files.update(p for p in data.rglob('*') if p.is_file())
    import csv
    for name, identity in dataset['files'].items():
        path = data/(name+'.csv')
        if sha(path) != identity['sha256']: raise ValueError('Frozen manifest changed')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                image = (ROOT/row['image_path']).resolve()
                if not image.is_relative_to(ROOT) or sha(image) != row['image_sha256']:
                    raise ValueError('Frozen image changed or escaped repository')
                files.add(image)
    for run in (ROOT/'experiments/checkpoints').iterdir():
        state_path = run/'state.json'
        if not state_path.exists(): continue
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['identity']['config'].get('data_version') != metadata['data_version']: continue
        if state['status'] != 'complete':
            raise ValueError('Finish active runs on this data before creating a stable archive')
        result = json.loads((ROOT/'experiments/reports'/run.name/'result.json').read_text(encoding='utf-8'))
        if sha(run/'best.keras') != result['checkpoint_sha256']:
            raise ValueError('Training checkpoint changed: '+run.name)
        for name in ['state.json','best.keras','latest.keras','installed-dependencies.lock', state.get('resume_checkpoint','latest.keras')]:
            path = run/name
            if path.exists(): files.add(path)
        files.update(p for p in (run/'code-snapshot').rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    destination = ROOT/'backups'
    destination.mkdir(exist_ok=True)
    output = destination/(metadata['model_version']+'-delivery.zip')
    ledger = destination/(metadata['model_version']+'-delivery-files.json')
    if output.exists() or ledger.exists(): raise ValueError('Archive already exists; preserve it')
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(files)}
    ledger_bytes = (json.dumps(hashes,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    pending = destination/(output.name+'.'+uuid.uuid4().hex+'.partial')
    with zipfile.ZipFile(pending,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for path in sorted(files):
            name = path.relative_to(ROOT).as_posix()
            if sha(path) != hashes[name]: raise ValueError('File changed during packaging: '+name)
            archive.write(path,name)
        archive.writestr('delivery-files.json',ledger_bytes)
    with zipfile.ZipFile(pending) as archive:
        for name, expected in hashes.items():
            with archive.open(name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest() != expected:
                    raise ValueError('Archive hash mismatch: '+name)
    pending.rename(output)
    with ledger.open('xb') as stream:
        stream.write(ledger_bytes)
    record = {'path':str(output),'bytes':output.stat().st_size,'sha256':sha(output),'files':len(hashes),'verified':True,'backup_scope':'local delivery copy; off-device backup still requires team destination'}
    (destination/(output.name+'.sha256')).write_text(record['sha256']+'  '+output.name+'\n',encoding='utf-8')
    report = ROOT/'experiments/reports/delivery'/metadata['model_version']
    report.mkdir(parents=True,exist_ok=True)
    (report/'archive.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
