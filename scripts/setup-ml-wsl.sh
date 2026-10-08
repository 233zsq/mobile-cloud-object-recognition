#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
data_version=${1:-}
train_env=$(realpath -m -- "${ML_TRAIN_ENV:-$repo/.venv-wsl}")
runtime_env=$(realpath -m -- "${ML_RUNTIME_ENV:-$repo/.venv-runtime-wsl}")
if [[ "$train_env" == "$runtime_env" ]]; then
  echo 'Training and independent runtime environments must use different directories.' >&2
  exit 2
fi
if ! command -v python3.12 >/dev/null 2>&1; then
  echo 'Ubuntu 24.04 requires python3.12 and python3.12-venv.'
  echo 'Run: sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv'
  exit 2
fi
python3.12 -m venv "$train_env"
"$train_env/bin/python" -m pip install -e './ml[gpu,runtime,test]' --constraint ml/constraints-training.txt
python3.12 -m venv "$runtime_env"
"$runtime_env/bin/python" -m pip install -r ml/requirements-runtime.txt
"$runtime_env/bin/python" -m pip install -e ml --no-deps
"$train_env/bin/python" -m pip check
"$runtime_env/bin/python" -m pip check
"$runtime_env/bin/python" -c 'import importlib.util; assert importlib.util.find_spec("tensorflow") is None, "Independent runtime environment contains TensorFlow"'
"$runtime_env/bin/python" -m pip freeze --exclude-editable > ml/requirements-wsl-runtime.lock
"$train_env/bin/python" - <<'PY'
import importlib.util
import sys
from pathlib import Path

# TensorFlow's official pip instructions link the NVIDIA wheel libraries here.
tensorflow_dir = Path(importlib.util.find_spec('tensorflow').origin).parent
links = [(tensorflow_dir / source.name, source)
         for source in sorted(tensorflow_dir.parent.glob('nvidia/*/lib/*.so*'))]
ptxas = tensorflow_dir.parent / 'nvidia/cuda_nvcc/bin/ptxas'
if ptxas.is_file():
    links.append((Path(sys.prefix) / 'bin/ptxas', ptxas))
for target, source in links:
    if target.is_symlink():
        if target.resolve() != source.resolve():
            raise ValueError('CUDA library link points elsewhere: ' + str(target))
    elif target.exists():
        raise ValueError('CUDA link destination is occupied: ' + str(target))
for target, source in links:
    if not target.is_symlink():
        target.symlink_to(source)
print('NVIDIA wheel library and compiler links verified:', len(links))
PY
ML_TRAIN_ENV="$train_env" source "$repo/scripts/activate-ml-wsl.sh"
"$train_env/bin/python" -m recognition doctor --training-check --require-gpu
"$train_env/bin/python" - "$data_version" <<'PY'
import sys
from recognition.common import ROOT, read_json, write_json
preflight = read_json(ROOT / 'experiments/reports/environment/preflight.json')
path = ROOT / 'ml/configs/baseline.json'
config = read_json(path)
if config['batch_size'] != preflight['recommended_common_batch']:
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
"$train_env/bin/python" -c 'import tensorflow as tf; assert tf.config.list_physical_devices("GPU"), "GPU not visible; do not mark environment validated"'
"$train_env/bin/python" -m pip freeze --exclude-editable > ml/requirements-wsl-gpu.lock
echo "GPU preflight passed. Training Python: $train_env/bin/python"
echo "Independent runtime Python: $runtime_env/bin/python"
echo 'Next run the synthetic smoke flow and the test suite on this environment.'
