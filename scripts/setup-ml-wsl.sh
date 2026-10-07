#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
data_version=${1:-}
if ! command -v python3.12 >/dev/null 2>&1; then
  echo 'Ubuntu 24.04 requires python3.12 and python3.12-venv.'
  echo 'Run: sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv'
  exit 2
fi
python3.12 -m venv .venv-wsl
"$repo/.venv-wsl/bin/python" -m pip install -e './ml[gpu,runtime,test]' --constraint ml/constraints-training.txt
python3.12 -m venv .venv-runtime-wsl
"$repo/.venv-runtime-wsl/bin/python" -m pip install -r ml/requirements-runtime.txt
"$repo/.venv-runtime-wsl/bin/python" -m pip install -e ml --no-deps
"$repo/.venv-runtime-wsl/bin/python" -m pip freeze --exclude-editable > ml/requirements-wsl-runtime.lock
"$repo/.venv-wsl/bin/python" -m recognition doctor --training-check --require-gpu
"$repo/.venv-wsl/bin/python" - "$data_version" <<'PY'
import sys
from recognition.common import ROOT, read_json, write_json
preflight = read_json(ROOT / 'experiments/reports/environment/preflight.json')
path = ROOT / 'ml/configs/baseline.json'
config = read_json(path)
config['batch_size'] = preflight['recommended_common_batch']
write_json(path, config)
print('Common batch for all newly generated GPU candidates:', config['batch_size'])
if sys.argv[1]:
    from recognition.data import load_split
    load_split(sys.argv[1], 'train')
    load_split(sys.argv[1], 'validation')
    config['data_version'] = sys.argv[1]
    config['category_version'] = read_json(ROOT/'data/splits'/sys.argv[1]/'dataset.json')['category_version']
    output = ROOT/'ml/configs'/('wsl-'+sys.argv[1]+'.json')
    write_json(output,config)
    print('GPU campaign config with the measured common batch:',output)
PY
"$repo/.venv-wsl/bin/python" -c 'import tensorflow as tf; assert tf.config.list_physical_devices("GPU"), "GPU not visible; do not mark environment validated"'
"$repo/.venv-wsl/bin/python" -m pip freeze --exclude-editable > ml/requirements-wsl-gpu.lock
echo 'GPU detected. Next run the same smoke and gradient tests on this environment.'
