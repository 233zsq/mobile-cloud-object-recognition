import shutil
import subprocess
import sys
from pathlib import Path

from recognition.common import read_json


def test_historical_report_does_not_replace_current_release(tmp_path):
    repo=Path(__file__).resolve().parents[2]
    campaign=Path('experiments/reports/pilot-cpu-20261007')
    winner=read_json(repo/campaign/'fine_tune-summary.json')['winner']
    paths=[
        Path('scripts/write-ml-report.py'),
        Path('ml/src/recognition/__init__.py'),
        Path('ml/src/recognition/common.py'),
        Path('data/manifests/public-reviewed.csv'),
        Path('experiments/reports/implementation-status.json'),
        Path('data/splits')/winner['config']['data_version']/'dataset.json',
        Path('experiments/reports')/(winner['experiment_id']+'-repeat43')/'result.json',
        *[campaign/(stage+'-summary.json') for stage in ('learning_rate','dropout','fine_tune')],
        *[Path('models/releases/pilot-cpu-tuned-v1')/name
          for name in ('metadata.json','validation-comparison.json')],
    ]
    for path in paths:
        destination=tmp_path/path
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(repo/path,destination)
    (tmp_path/'docs').mkdir()
    status=tmp_path/'experiments/reports/implementation-status.json'
    original=status.read_bytes()
    result=subprocess.run([sys.executable,str(tmp_path/'scripts/write-ml-report.py')],
                          cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'docs/ml-experiments.md').is_file()
    assert status.read_bytes()==original
