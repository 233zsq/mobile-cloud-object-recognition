"""Generate an unfilled device result form; never copies golden scores as evidence."""
import argparse
from pathlib import Path
from recognition.common import read_json, write_json

p=argparse.ArgumentParser()
p.add_argument('--release',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--mode',choices=['reference_tensor','image_chain'],required=True)
a=p.parse_args()
if a.out.exists(): raise SystemExit('Output exists; preserve submitted evidence and choose a new file')
m=read_json(a.release/'metadata.json')
examples=read_json(a.release/'examples/manifest.json')
samples=[]
for e in examples:
    sample={'sample_id':e['sample_id'],'scores':[None]*10}
    if a.mode=='reference_tensor':sample['tensor_sha256']='REPLACE_WITH_HASH_OF_ACTUAL_INPUT_BYTES'
    else:sample['tensor_file']=e['sample_id']+'.bin'
    samples.append(sample)
write_json(a.out,{'run_id':'REPLACE_WITH_UNIQUE_DEVICE_RUN_ID','mode':a.mode,'device':'REPLACE_WITH_ACTUAL_DEVICE_OS','runtime':'REPLACE_WITH_RUNTIME_VERSION_THREADS','model_sha256':m['sha256'],'labels_sha256':m['labels_sha256'],'input_contract':m['input'],'samples':samples})
print(a.out)
