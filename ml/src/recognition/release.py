"""FP32 export, full-validation comparison, independent evaluation and timing."""
import shutil
import hashlib
import json
import tempfile
import time
from pathlib import Path
import numpy as np
from .common import ROOT, categories, digest, image_path, now, read_csv, read_json, safe_name, write_json
from .data import check_isolation, load_split
from .inference import LiteRunner
from .preprocessing import SPEC, preprocess
from .training import configure_fp32, metrics, predict, prepare


def export(result_path,version,formal=False,reproduction=None,additional_reproduction=None):
    import tensorflow as tf
    import keras
    configure_fp32()
    result=read_json(result_path)
    safe_name(version)
    if formal and (result["status"]!="complete" or not reproduction):
        raise ValueError("Formal package requires completed primary and reproduction runs")
    if result["config"]["seed"]!=42:
        raise ValueError("Release primary must use seed 42")
    if formal:
        preflight=read_json(ROOT/'experiments/reports/environment/preflight.json')
        if not result.get('environment',{}).get('gpu') or preflight.get('status')!='gpu_passed' or preflight.get('recommended_common_batch')!=result['config']['batch_size']:
            raise ValueError('Formal release requires successful GPU training and matching GPU batch preflight')
        repeat=read_json(reproduction)
        validate_parent_reproduction(result,repeat)
        a,b=dict(result["config"]),dict(repeat["config"])
        a.pop("seed");b.pop("seed")
        if repeat["status"]!="complete" or repeat["config"]["seed"]!=43 or a!=b or repeat["identity"]["code_snapshot_sha256"]!=result["identity"]["code_snapshot_sha256"] or repeat["identity"]["data_metadata_sha256"]!=result["identity"]["data_metadata_sha256"]:
            raise ValueError("Reproduction missing or config/code/data differs")
        if {k:v for k,v in repeat["environment"].items() if k!="platform"}!={k:v for k,v in result["environment"].items() if k!="platform"}:
            raise ValueError("Reproduction runtime/environment differs from primary")
        gap=abs(result["validation"]["macro_f1"]-repeat["validation"]["macro_f1"])
        if gap>.05:
            if not additional_reproduction:
                raise ValueError("F1 gap > .05; investigate and provide --additional-reproduction seed44")
            extra=read_json(additional_reproduction)
            validate_parent_reproduction(result,extra)
            c=dict(extra["config"]);c.pop("seed")
            if extra["status"]!="complete" or extra["config"]["seed"]!=44 or c!=a or extra["identity"]["code_snapshot_sha256"]!=result["identity"]["code_snapshot_sha256"] or extra["identity"]["data_metadata_sha256"]!=result["identity"]["data_metadata_sha256"]:
                raise ValueError("Additional seed44 reproduction is incompatible")
            if {k:v for k,v in extra["environment"].items() if k!="platform"}!={k:v for k,v in result["environment"].items() if k!="platform"}:
                raise ValueError("Additional reproduction runtime differs from primary")
    directory=ROOT/"models/releases"/version
    if directory.exists():
        raise ValueError("Release version exists; do not overwrite")
    checkpoint=ROOT/result["checkpoint"]
    if digest(checkpoint)!=result["checkpoint_sha256"]:
        raise ValueError("Checkpoint changed")
    model=keras.models.load_model(checkpoint)
    directory.mkdir(parents=True,exist_ok=True)
    # Windows TF gfile rejects this repository's CJK path. Only its native
    # SavedModel IO runs in an ASCII temporary directory; Python copies back.
    with tempfile.TemporaryDirectory(prefix="campus-export-") as staging:
        saved=Path(staging)/"saved_model"
        model.export(str(saved),input_signature=[tf.TensorSpec([1,224,224,3],tf.float32)],verbose=False)
        converter=tf.lite.TFLiteConverter.from_saved_model(str(saved))
        converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS]
        converter.optimizations=[]
        blob=converter.convert()
        shutil.copytree(saved,directory/"saved_model")
    (directory/"model.tflite").write_bytes(blob)
    cat=categories(result["config"]["category_version"])
    (directory/"labels.txt").write_text("\n".join(c["label_key"] for c in cat["categories"])+"\n",encoding="utf-8")
    metadata={"status":"validation_pending","requested_status":"formal" if formal else "experimental","model_version":version,"model_file":"model.tflite","sha256":digest(directory/"model.tflite"),"labels_file":"labels.txt","labels_sha256":digest(directory/"labels.txt"),"category_version":cat["category_version"],"categories":cat["categories"],"data_version":result["config"]["data_version"],"experiment_id":result["experiment_id"],"code_commit":result["code_commit"],"code_snapshot_sha256":result["identity"]["code_snapshot_sha256"],"input":SPEC,"output":{"shape":[1,10],"dtype":"float32","interpretation":"softmax"},"low_confidence_threshold":result["threshold"]["threshold"],"threshold_status":result["threshold"]["status"],"created_at":now(),"model_bytes":len(blob),"acceptance":{"size_passed":len(blob)<=15000000,"independent_field_accuracy":"pending","android_latency":"pending","android_consistency":"pending","actual_cloud_consistency":"pending"},"export_environment":result["environment"],"checkpoint_sha256":result["checkpoint_sha256"]}
    write_json(directory/"metadata.json",metadata)
    if result['identity'].get('parent_lineage'):
        metadata['parent_lineage']=result['identity']['parent_lineage']
        metadata['deployment_approval']='pending_human_approval'
        write_json(directory/'metadata.json',metadata)
    if formal:
        write_json(directory/"reproduction.json",{"seed42":result["validation"],"seed43":repeat["validation"],"macro_f1_gap":gap,"seed44":extra["validation"] if gap>.05 else None,"variability_warning":gap>.05})
    runner=LiteRunner(directory,_allow_pending=True)
    rows,_=load_split(metadata["data_version"],"validation")
    x,y=prepare(rows)
    original=predict(model,x)
    lite=np.stack([runner.predict_tensor(a) for a in x])
    difference=float(np.max(np.abs(original-lite)))
    changes=[rows[i]["sample_id"] for i in np.flatnonzero(original.argmax(axis=1)!=lite.argmax(axis=1))]
    comparison={"sample_count":len(rows),"max_score_difference":difference,"top1_mismatch_sample_ids":changes,"tolerance":.001,"passed":not changes and difference<=.001}
    write_json(directory/"validation-comparison.json",comparison)
    write_json(directory/"evaluation-validation.json",{"split":"validation","selection_data":True,"metrics":metrics(y,lite),"model_sha256":metadata["sha256"]})
    examples=[]
    counts={i:0 for i in range(10)}
    fixture_dir=directory/"examples"
    fixture_dir.mkdir()
    for i,row in enumerate(rows):
        category=int(row["category_id"])
        if counts[category]>=2:
            continue
        sid=safe_name(row["sample_id"])
        image_file=sid+image_path(row["image_path"]).suffix
        shutil.copyfile(image_path(row["image_path"]),fixture_dir/image_file)
        x[i].astype("<f4").tofile(fixture_dir/(sid+".bin"))
        examples.append({"sample_id":sid,"category_id":category,"image":image_file,"tensor":sid+".bin","image_sha256":digest(fixture_dir/image_file),"tensor_sha256":digest(fixture_dir/(sid+".bin")),"scores":lite[i].tolist(),"predicted_id":int(lite[i].argmax()),"source_url":row.get("source_url",""),"author":row.get("author",""),"license":row.get("license",""),"license_url":row.get("license_url","")})
        counts[category]+=1
    write_json(fixture_dir/"manifest.json",examples)
    eligible=comparison["passed"] and len(blob)<=15000000 and all(c>=2 for c in counts.values())
    metadata["status"]="frozen" if formal and eligible else "experimental" if eligible else "verification_failed"
    metadata["final_test_status"]="pending_field_photos"
    write_json(directory/"metadata.json",metadata)
    write_json(directory/"release-files.json",{p.relative_to(directory).as_posix():digest(p) for p in sorted(directory.rglob("*")) if p.is_file() and "saved_model" not in p.parts and p.name!="release-files.json"})
    return directory


def validate_parent_reproduction(primary,repeat):
    """Fixed-parent repeats must start from exactly the same verified weights."""
    if primary['config'].get('training_mode')!='parent_finetune':
        return
    from .evolution import resolve_parent
    _,expected=resolve_parent(primary['config'])
    for result in (primary,repeat):
        if result['identity'].get('parent_lineage')!=expected or result['identity'].get('initial_checkpoint_sha256')!=expected['checkpoint_sha256']:
            raise ValueError('Reproduction parent lineage/checkpoint differs')


def compare_external(release,report_path):
    release,report_path=Path(release),Path(report_path)
    meta=read_json(release/'metadata.json'); report=read_json(report_path)
    if report.get('model_sha256')!=meta['sha256'] or report.get('labels_sha256')!=meta['labels_sha256']:
        raise ValueError('External model/labels SHA-256 mismatch')
    if report.get('input_contract')!=meta['input']:
        raise ValueError('External preprocessing/type/normalization contract differs')
    mode=report.get('mode')
    if mode not in ('reference_tensor','image_chain'):
        raise ValueError('External mode must be reference_tensor or image_chain')
    run_id=safe_name(report.get('run_id',''))
    if any(not isinstance(report.get(k),str) or not report[k].strip() or report[k].startswith('REPLACE_') for k in ('device','runtime')):
        raise ValueError('External evidence requires actual device and runtime details')
    expected={e['sample_id']:e for e in read_json(release/'examples/manifest.json')}
    samples=report.get('samples',[])
    if len(samples)!=len(expected) or {s['sample_id'] for s in samples}!=set(expected):
        raise ValueError('External report must contain each handover sample exactly once')
    comparisons=[]
    for sample in samples:
        golden=expected[sample['sample_id']]
        scores=np.asarray(sample['scores'],dtype=np.float64)
        if scores.shape!=(10,) or not np.isfinite(scores).all() or np.any(scores<0) or np.any(scores>1) or not np.isclose(scores.sum(),1,atol=1e-4):
            raise ValueError('Invalid external ten-class Softmax scores')
        if mode=='reference_tensor':
            input_passed=sample.get('tensor_sha256')==golden['tensor_sha256']
            input_difference=None
            actual_tensor_sha256=sample.get('tensor_sha256')
        else:
            path=(report_path.parent/sample['tensor_file']).resolve()
            if not path.is_relative_to(report_path.parent.resolve()) or path.stat().st_size!=602112:
                raise ValueError('External tensor path/byte count invalid')
            actual=np.fromfile(path,dtype='<f4').reshape(224,224,3)
            reference=np.fromfile(release/'examples'/golden['tensor'],dtype='<f4').reshape(224,224,3)
            if not np.isfinite(actual).all() or actual.min()<0 or actual.max()>255:
                raise ValueError('External image input is not raw finite float32 0..255')
            input_difference=float(np.max(np.abs(actual-reference)))
            input_passed=input_difference<=.001
            actual_tensor_sha256=digest(path)
        difference=float(np.max(np.abs(scores-golden['scores'])))
        same=int(scores.argmax())==golden['predicted_id']
        comparisons.append({'sample_id':sample['sample_id'],'actual_tensor_sha256':actual_tensor_sha256,'reference_tensor_sha256':golden['tensor_sha256'],'input_passed':input_passed,'max_input_difference':input_difference,'top1_same':same,'max_score_difference':difference,'passed':bool(input_passed and same and difference<=.001)})
    result={'at':now(),'run_id':run_id,'mode':mode,'device':report.get('device'),'runtime':report.get('runtime'),'model_sha256':meta['sha256'],'labels_sha256':meta['labels_sha256'],'submitted_report_sha256':digest(report_path),'passed':all(c['passed'] for c in comparisons),'comparisons':comparisons}
    path=ROOT/'experiments/reports/consistency'/meta['model_version']/(run_id+'.json')
    if path.exists():raise ValueError('Consistency evidence exists; use a new run_id')
    write_json(path.with_name(run_id+'-submitted.json'),report)
    write_json(path,result)
    if not result['passed']:
        raise ValueError('External input/Top-1/score differences failed; inspect '+str(path))
    return result


def verify(release,external_report=None,*,_annex_recovery=None):
    release=Path(release)
    runner=LiteRunner(release)
    files=read_json(release/"release-files.json")
    mutable={"metadata.json","evaluation-test.json","confusion-matrix-test.png"}
    if _annex_recovery:
        # Only a validated, interrupted test annex may change these three files.
        # Model, labels, contract and all golden samples still undergo verification.
        if runner.metadata not in (_annex_recovery['original_metadata'],_annex_recovery['metadata']) or files not in (_annex_recovery['original_files'],_annex_recovery['files']):
            raise ValueError('Interrupted evaluation release identity differs')
        files=_annex_recovery['original_files']
    for filename,sha in files.items():
        path=(release/filename).resolve()
        if not path.is_relative_to(release.resolve()) or (not (_annex_recovery and filename in mutable) and digest(path)!=sha):
            raise ValueError("Release file hash mismatch: "+filename)
    examples=read_json(release/"examples/manifest.json")
    if runner.metadata["status"] not in ("experimental","frozen") or (release/"model.tflite").stat().st_size!=runner.metadata["model_bytes"] or runner.metadata["model_bytes"]>15000000:
        raise ValueError("Release status/actual model size failed the package contract")
    if len(examples)<20 or any(sum(e["category_id"]==i for e in examples)<2 for i in range(10)):
        raise ValueError("Handover examples need at least two per class and twenty total")
    max_difference=0
    for example in examples:
        path=release/"examples"/example["tensor"]
        array=np.fromfile(path,dtype="<f4").reshape(224,224,3)
        scores=runner.predict_tensor(array)
        diff=float(np.max(np.abs(scores-example["scores"])))
        max_difference=max(max_difference,diff)
        if scores.argmax()!=example["predicted_id"] or diff>.001:
            raise ValueError("Golden tensor prediction mismatch")
        if not np.array_equal(preprocess(release/"examples"/example["image"]),array):
            raise ValueError("Golden image preprocessing differs")
    result={"passed":True,"example_count":len(examples),"max_score_difference":max_difference,"runtime":"ai-edge-litert", "model_status":runner.metadata["status"]}
    if external_report:result['external']=compare_external(release,external_report)
    return result


def tested_image_hashes(record):
    hashes=record.get('image_sha256s')
    if hashes is None:
        # Older reports can recover photo identities from their unchanged frozen CSV,
        # without reading the historical test images or changing the old evidence.
        version=safe_name(record.get('data_version',''))
        path=ROOT/'data/splits'/version/'test.csv'
        if not path.is_file() or digest(path)!=record.get('manifest_sha256'):
            raise ValueError('Historical test photo identities unavailable; restore the original frozen test.csv')
        hashes=[row.get('image_sha256') for row in read_csv(path)]
    if not isinstance(hashes,list) or not hashes or any(not isinstance(value,str) or not value for value in hashes):
        raise ValueError('Historical test photo SHA-256 identities are missing or invalid')
    return set(hashes)


def check_test_model_binding(version,manifest_sha256,model_sha256,rows):
    incoming={row['image_sha256'] for row in rows}
    for path in (ROOT/'experiments/reports/evaluations').glob('*/*-test.json'):
        previous=read_json(path)
        if previous.get('split')!='test' or previous.get('model_sha256')==model_sha256:
            continue
        if previous.get('data_version')==version or previous.get('manifest_sha256')==manifest_sha256:
            raise ValueError('Independent test version was already used by a different model; freeze a new test version')
        if incoming & tested_image_hashes(previous):
            raise ValueError('Independent test photos were already used by a different model; collect new independent photos')


def release_identity(metadata):
    # Acceptance evidence may be appended after freezing; all model, label,
    # preprocessing, threshold and training identity fields remain immutable.
    stable={key:value for key,value in metadata.items() if key not in ('acceptance','field_test')}
    return hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def validate_legacy_release_identity(result,release,directory,metadata):
    original=result.get('release_metadata_sha256')
    if original is None or original==digest(release/'metadata.json'):
        return
    # Reports created before stable identities can recover the original package
    # snapshot from the test annex journal, without modifying the first report.
    for path in directory.glob('*-test-handover.json'):
        saved=read_json(path)
        report=path.with_name(path.name.removesuffix('-handover.json')+'.json')
        if saved.get('original_metadata_sha256')!=original or not report.is_file() or digest(report)!=saved.get('report_sha256'):
            continue
        snapshot=saved['original_metadata']
        encoded=json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n'
        if original not in (hashlib.sha256(encoded.encode('utf-8')).hexdigest(),hashlib.sha256(encoded.replace('\n','\r\n').encode('utf-8')).hexdigest()):
            raise ValueError('Historical evaluation metadata snapshot hash differs')
        if release_identity(snapshot)==release_identity(metadata):
            return
    raise ValueError('Existing evaluation release identity differs')


def validate_cached_evaluation(result,metadata,version,split,rows,manifest_sha256):
    expected={'split':split,'model_sha256':metadata['sha256'],
              'model_version':metadata['model_version'],'data_version':version,
              'manifest_sha256':manifest_sha256}
    if any(result.get(key)!=value for key,value in expected.items()) or ('labels_sha256' in result and result['labels_sha256']!=metadata.get('labels_sha256')):
        raise ValueError('Existing evaluation identity differs; preserve the first evidence')
    if 'release_identity_sha256' in result and result['release_identity_sha256']!=release_identity(metadata):
        raise ValueError('Existing evaluation release identity differs')
    predictions=result.get('predictions',[])
    if len(predictions)!=len(rows) or any(p.get('sample_id')!=r['sample_id'] or p.get('true_id')!=int(r['category_id']) or p.get('predicted_id') not in range(10) or not np.isfinite(p.get('confidence',np.nan)) or not 0<=p['confidence']<=1 for p,r in zip(predictions,rows)):
        raise ValueError('Existing evaluation sample identity/predictions differ')
    if split=='test' and tested_image_hashes(result)!={r['image_sha256'] for r in rows}:
        raise ValueError('Existing evaluation photo identity differs')


def render_evaluation(out,result,rows,labels):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,8))
    matrix=np.array(result["metrics"]["confusion_matrix"])
    image=ax.imshow(matrix,cmap="Blues")
    ax.set(xticks=range(10),yticks=range(10),xticklabels=labels,yticklabels=labels,xlabel="Predicted",ylabel="Actual",title=result['split'])
    plt.setp(ax.get_xticklabels(),rotation=45,ha="right")
    for i in range(10):
        for j in range(10):
            ax.text(j,i,str(matrix[i,j]),ha="center",va="center",color="white" if matrix[i,j]>matrix.max()/2 else "black")
    fig.colorbar(image,ax=ax)
    try:
        fig.tight_layout();fig.savefig(out.with_suffix(".png"),dpi=160)
    finally:
        plt.close(fig)
    from PIL import Image,ImageOps,ImageDraw
    predictions=result['predictions']
    wrong=[i for i,p in enumerate(predictions) if p['predicted_id']!=p['true_id']]
    if wrong:
        selected=wrong[:40]
        sheet=Image.new("RGB",(1000,220*((len(selected)+4)//5)),"white")
        draw=ImageDraw.Draw(sheet)
        for j,i in enumerate(selected):
            left,top=(j%5)*200,(j//5)*220
            with Image.open(image_path(rows[i]["image_path"])) as original:
                thumb=ImageOps.exif_transpose(original).convert("RGB");thumb.thumbnail((190,170))
                sheet.paste(thumb,(left+(190-thumb.width)//2,top))
            draw.text((left+3,top+173),rows[i]["sample_id"],fill="black")
            draw.text((left+3,top+189),f"true={labels[predictions[i]['true_id']]} / pred={labels[predictions[i]['predicted_id']]}",fill="black")
        sheet.save(out.with_name(out.stem+"-errors.png"))


def annex_evaluation(release,out,result,metadata,journal_path):
    if journal_path.exists():
        journal=read_json(journal_path)
    else:
        updated={**metadata,'acceptance':{**metadata['acceptance'],
                 'independent_field_accuracy':{'accuracy':result['metrics']['accuracy'],
                 'macro_f1':result['metrics']['macro_f1'],**result['acceptance']}},
                 'field_test':{'data_version':result['data_version'],
                 'manifest_sha256':result['manifest_sha256'],'evaluated_at':result['at']}}
        original_files=read_json(release/'release-files.json')
        with tempfile.TemporaryDirectory(prefix='campus-annex-',dir=out.parent) as staging:
            path=Path(staging)/'metadata.json'
            write_json(path,updated)
            files={**original_files,'metadata.json':digest(path),
                   'evaluation-test.json':digest(out),'confusion-matrix-test.png':digest(out.with_suffix('.png'))}
        journal={'report_sha256':digest(out),'original_metadata_sha256':digest(release/'metadata.json'),'original_metadata':metadata,
                 'metadata':updated,'original_files':original_files,'files':files}
        # Persist both valid package states before changing any annex file.
        write_json(journal_path,journal)
    for source,name in ((out,'evaluation-test.json'),(out.with_suffix('.png'),'confusion-matrix-test.png')):
        if digest(source)!=journal['files'][name]:
            raise ValueError('Interrupted evaluation artifact hash differs')
        target=release/name
        temporary=target.with_name(target.name+'.tmp')
        shutil.copyfile(source,temporary);temporary.replace(target)
    write_json(release/'metadata.json',journal['metadata'])
    write_json(release/'release-files.json',journal['files'])


def evaluate(release,split="validation",test_version=None,confirm_model_hash=None):
    release=Path(release)
    runner=LiteRunner(release)
    m=runner.metadata
    version=test_version or m["data_version"]
    if split=="test" and (m["status"]!="frozen" or confirm_model_hash!=m["sha256"]):
        raise ValueError("Final test requires frozen model and explicit --confirm-model-hash")
    rows,data=load_split(version,split,allow_test=split=="test")
    out=ROOT/"experiments/reports/evaluations"/safe_name(m["model_version"])/f"{version}-{split}.json"
    completion=out.with_name(out.stem+'-completion.json')
    journal_path=out.with_name(out.stem+'-handover.json')
    result=read_json(out) if out.exists() else None
    if result is not None:
        validate_cached_evaluation(result,m,version,split,rows,data['files'][split]['sha256'])
    if split=="test":
        check_test_model_binding(version,data['files']['test']['sha256'],m['sha256'],rows)
        if any(r.get("source_dataset") not in ("field","self_captured") or not r.get("object_id") for r in rows) or any(sum(int(r["category_id"])==i for r in rows)<20 for i in range(10)):
            raise ValueError("Final test requires at least twenty independently captured photos per class")
        train,_=load_split(m["data_version"],"train")
        val,_=load_split(m["data_version"],"validation")
        check_isolation(train,val,rows)
    journal=None
    if journal_path.exists():
        journal=read_json(journal_path)
        if result is None or journal['report_sha256']!=digest(out) or ('release_metadata_sha256' in result and result['release_metadata_sha256']!=journal['original_metadata_sha256']):
            raise ValueError('Interrupted evaluation evidence hash differs')
    if result is not None and 'release_identity_sha256' not in result:
        validate_legacy_release_identity(result,release,out.parent,m)
    verify(release,_annex_recovery=journal if not completion.exists() else None)
    if completion.exists():
        finished=read_json(completion)
        if result is None or finished['report_sha256']!=digest(out) or any(not (out.parent/name).resolve().is_relative_to(out.parent.resolve()) or digest(out.parent/name)!=sha for name,sha in finished['artifacts'].items()):
            raise ValueError('Completed evaluation artifact hash differs')
        return result
    if result is None:
        x,y=prepare(rows)
        scores=np.stack([runner.predict_tensor(a) for a in x])
        result={"at":now(),"split":split,"model_sha256":m["sha256"],"labels_sha256":m.get('labels_sha256'),"release_metadata_sha256":digest(release/'metadata.json'),"release_identity_sha256":release_identity(m),"model_version":m["model_version"],"data_version":version,"manifest_sha256":data["files"][split]["sha256"],"metrics":metrics(y,scores),"predictions":[{"sample_id":r["sample_id"],"true_id":int(y[i]),"predicted_id":int(scores[i].argmax()),"confidence":float(scores[i].max())} for i,r in enumerate(rows)]}
        result['error_sample_ids']=[p['sample_id'] for p in result['predictions'] if p['true_id']!=p['predicted_id']]
        if split=="test":
            result['image_sha256s']=sorted(row['image_sha256'] for row in rows)
            result["acceptance"]={"accuracy_passed":result["metrics"]["accuracy"]>=.85,"macro_f1_passed":result["metrics"]["macro_f1"]>=.8}
        # First predictions and metrics are immutable, including during recovery.
        write_json(out,result)
    if journal is None:
        render_evaluation(out,result,rows,runner.labels)
    if split=='test':
        annex_evaluation(release,out,result,m,journal_path)
        verify(release)
    artifacts=[out.with_suffix('.png')]
    errors=out.with_name(out.stem+'-errors.png')
    if errors.exists():artifacts.append(errors)
    write_json(completion,{'at':now(),'report_sha256':digest(out),
                          'artifacts':{p.name:digest(p) for p in artifacts}})
    return result


def benchmark(release,threads=1,warmup=20,iterations=100):
    if warmup<20 or iterations<100:
        raise ValueError("Require at least 20 warmups and 100 timed iterations")
    runner=LiteRunner(release,threads)
    examples=read_json(Path(release)/"examples/manifest.json")
    paths=[Path(release)/"examples"/e["image"] for e in examples]
    arrays=[preprocess(p) for p in paths]
    for i in range(warmup):
        runner.predict_tensor(arrays[i%len(arrays)])
    inference,total=[],[]
    for i in range(iterations):
        start=time.perf_counter()
        runner.predict_tensor(arrays[i%len(arrays)])
        inference.append((time.perf_counter()-start)*1000)
        start=time.perf_counter()
        runner.predict_tensor(preprocess(paths[i%len(paths)]))
        total.append((time.perf_counter()-start)*1000)
    import platform
    value={"at":now(),"platform":platform.platform(),"processor":platform.processor(),"runtime":"ai-edge-litert","threads":threads,"warmup":warmup,"iterations":iterations,"model_bytes":runner.metadata["model_bytes"],"inference_ms":{"p50":float(np.percentile(inference,50)),"p95":float(np.percentile(inference,95))},"preprocess_and_inference_ms":{"p50":float(np.percentile(total,50)),"p95":float(np.percentile(total,95))},"network_wait_ms":None,"location":"local CPU; not actual cloud or Android"}
    write_json(ROOT/"experiments/reports/benchmarks"/runner.metadata["model_version"]/f"local-cpu-{threads}threads.json",value)
    return value
