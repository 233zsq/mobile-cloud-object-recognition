import shutil
import os
import subprocess
import sys
from pathlib import Path

import pytest
from recognition.common import read_json,write_json


@pytest.mark.parametrize('campaign_name,version,script_name,document',[
    ('pilot-cpu-20261007','pilot-cpu-tuned-v1','write-ml-report.py','ml-experiments.md'),
    ('expanded-cpu-20261007','expanded-cpu-v1','write-expanded-ml-report.py','ml-expanded-experiments.md'),
])
@pytest.mark.parametrize('selected',['expanded-cpu-v1','campus-gpu-v1'])
def test_historical_report_does_not_replace_current_release(tmp_path,campaign_name,version,script_name,document,selected):
    repo=Path(__file__).resolve().parents[2]
    campaign=Path('experiments/reports')/campaign_name
    winner=read_json(repo/campaign/'fine_tune-summary.json')['winner']
    paths=[
        Path('scripts')/script_name,
        Path('data/manifests/public-reviewed.csv'),
        Path('shared/categories.json'),
        Path('experiments/reports/implementation-status.json'),
        Path('data/splits')/winner['config']['data_version']/'dataset.json',
        Path('experiments/reports')/(winner['experiment_id']+'-repeat43')/'result.json',
        *[campaign/(stage+'-summary.json') for stage in ('learning_rate','dropout','fine_tune')],
        *[Path('models/releases')/version/name
          for name in ('metadata.json','validation-comparison.json')],
    ]
    if script_name=='write-expanded-ml-report.py':
        paths.extend([Path('experiments/reports/benchmarks')/version/'local-cpu-1threads.json',
                      Path('experiments/reports/audit/final-public-data.json')])
    shutil.copytree(repo/'ml/src/recognition',tmp_path/'ml/src/recognition',ignore=shutil.ignore_patterns('__pycache__'))
    for path in paths:
        destination=tmp_path/path
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(repo/path,destination)
    (tmp_path/'docs').mkdir()
    status=tmp_path/'experiments/reports/implementation-status.json'
    live=read_json(status)
    if selected=='campus-gpu-v1':
        live['release'].update(selected=selected,status='frozen',model_sha256='gpu-model-sha',model_bytes=9000000)
        live['acceptance']['independent_field_accuracy_and_f1']='passed'
        write_json(status,live)
    original=status.read_bytes()
    environment={**os.environ,'RECOGNITION_ROOT':str(tmp_path),'PYTHONPATH':str(tmp_path/'ml/src')}
    result=subprocess.run([sys.executable,str(tmp_path/'scripts'/script_name)],
                          cwd=tmp_path,env=environment,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'docs'/document).is_file()
    assert status.read_bytes()==original
