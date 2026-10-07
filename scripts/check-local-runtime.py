"""Exercise independent LiteRT and device report verification on this PC only."""
import argparse
import importlib.metadata
import importlib.util
import platform
import sys
from pathlib import Path

import numpy as np
from recognition.common import ROOT, read_json, write_json, digest, now, safe_name
from recognition.inference import LiteRunner
from recognition.preprocessing import preprocess
from recognition.release import verify

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--release', type=Path, required=True)
parser.add_argument('--run-id', required=True)
args = parser.parse_args()
run_id = safe_name(args.run_id)
if importlib.util.find_spec('tensorflow') is not None:
    raise SystemExit('Use a separate environment without TensorFlow installed')
release = args.release.resolve()
meta = read_json(release/'metadata.json')
examples = read_json(release/'examples/manifest.json')
root = ROOT/'experiments/checkpoints/local-runtime'/run_id
if root.exists():
    raise SystemExit('Run exists; preserve evidence and choose a new run ID')
root.mkdir(parents=True)
runner = LiteRunner(release)
results = []
for mode in ['reference_tensor', 'image_chain']:
    directory = root/mode
    directory.mkdir()
    report = {
        'run_id': run_id+'-'+mode, 'mode': mode,
        'device': platform.platform()+' LOCAL PC CHECK ONLY',
        'runtime': 'ai-edge-litert '+importlib.metadata.version('ai-edge-litert')+'; one thread',
        'model_sha256': meta['sha256'], 'labels_sha256': meta['labels_sha256'],
        'input_contract': meta['input'], 'samples': [],
    }
    for example in examples:
        tensor = (np.fromfile(release/'examples'/example['tensor'], dtype='<f4').reshape(224,224,3)
                  if mode == 'reference_tensor' else preprocess(release/'examples'/example['image']))
        path = directory/(example['sample_id']+'.bin')
        tensor.astype('<f4').tofile(path)
        row = {'sample_id': example['sample_id'], 'scores': runner.predict_tensor(tensor).tolist()}
        row.update({'tensor_sha256': digest(path)} if mode == 'reference_tensor' else {'tensor_file': path.name})
        report['samples'].append(row)
    report_path = directory/'result.json'
    write_json(report_path, report)
    results.append(verify(release, report_path))
assert 'tensorflow' not in sys.modules
evidence = {
    'at': now(), 'run_id': run_id, 'tensorflow_installed': False, 'tensorflow_imported': False,
    'scope': 'Local independent CPU runtime and checker verification; Android/cloud acceptance pending',
    'python': platform.python_version(), 'runtime': importlib.metadata.version('ai-edge-litert'),
    'model_version': meta['model_version'], 'model_sha256': meta['sha256'], 'results': results,
}
output = ROOT/'experiments/reports/environment'/(run_id+'.json')
write_json(output, evidence)
print(output)
