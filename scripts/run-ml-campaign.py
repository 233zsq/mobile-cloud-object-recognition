"""Sequential stages, reproduction, export and verification; safely rerunnable after pause."""
import argparse
from pathlib import Path
from recognition.common import ROOT,read_json
from recognition.training import sweep,summarize,reproduce
from recognition.release import export,verify,evaluate,benchmark

p=argparse.ArgumentParser()
p.add_argument('--config',type=Path,required=True)
p.add_argument('--campaign',required=True)
p.add_argument('--version',required=True)
p.add_argument('--formal',action='store_true')
a=p.parse_args()
previous=None
for stage in ['learning_rate','dropout','fine_tune']:
    jobs_path=sweep(a.config,a.campaign,stage,previous,execute=True)
    jobs=read_json(jobs_path)
    if any(not (ROOT/'experiments/reports'/j['experiment_id']/'result.json').exists() for j in jobs['jobs']):
        raise SystemExit('Paused with checkpoints saved; rerun this command during 06:00–23:00 Beijing time')
    previous=summarize(jobs_path)
winner=read_json(previous)['winner']
primary=ROOT/'experiments/reports'/winner['experiment_id']/'result.json'
repeated=reproduce(primary,43)
if repeated.get('status')=='paused_time_window':raise SystemExit('Reproduction paused; rerun the same command')
repeat_path=ROOT/'experiments/reports'/repeated['experiment_id']/'result.json'
extra_path=None
if abs(winner['validation']['macro_f1']-repeated['validation']['macro_f1'])>.05:
    extra=reproduce(primary,44)
    if extra.get('status')=='paused_time_window':raise SystemExit('Seed44 paused; rerun the same command')
    extra_path=ROOT/'experiments/reports'/extra['experiment_id']/'result.json'
release=ROOT/'models/releases'/a.version
if not release.exists():export(primary,a.version,a.formal,repeat_path,extra_path)
meta=read_json(release/'metadata.json')
if meta['experiment_id']!=winner['experiment_id'] or meta['checkpoint_sha256']!=winner['checkpoint_sha256'] or (a.formal and meta['status']!='frozen'):
    raise SystemExit('Existing release differs or has failed checks; choose a new version')
print(verify(release),flush=True)
evaluate(release)
benchmark(release)
print('Completed '+str(release)+'; independent field and actual Android/cloud checks remain separate',flush=True)
