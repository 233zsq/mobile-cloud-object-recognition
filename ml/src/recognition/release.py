"""FP32 export, full-validation comparison, independent evaluation and timing."""
import shutil
import tempfile
import time
from pathlib import Path
import numpy as np
from .common import ROOT, categories, digest, image_path, now, read_json, safe_name, write_json
from .data import check_isolation, load_split
from .inference import LiteRunner
from .preprocessing import SPEC, preprocess
from .training import metrics, predict, prepare


def export(result_path,version,formal=False,reproduction=None,additional_reproduction=None):
    import tensorflow as tf
    import keras
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


def verify(release,external_report=None):
    release=Path(release)
    runner=LiteRunner(release)
    files=read_json(release/"release-files.json")
    for filename,sha in files.items():
        path=(release/filename).resolve()
        if not path.is_relative_to(release.resolve()) or digest(path)!=sha:
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


def evaluate(release,split="validation",test_version=None,confirm_model_hash=None):
    release=Path(release)
    verify(release)
    runner=LiteRunner(release)
    m=runner.metadata
    version=test_version or m["data_version"]
    if split=="test" and (m["status"]!="frozen" or confirm_model_hash!=m["sha256"]):
        raise ValueError("Final test requires frozen model and explicit --confirm-model-hash")
    rows,data=load_split(version,split,allow_test=split=="test")
    if split=="test":
        if any(r.get("source_dataset") not in ("field","self_captured") or not r.get("object_id") for r in rows) or any(sum(int(r["category_id"])==i for r in rows)<20 for i in range(10)):
            raise ValueError("Final test requires at least twenty independently captured photos per class")
        train,_=load_split(m["data_version"],"train")
        val,_=load_split(m["data_version"],"validation")
        check_isolation(train,val,rows)
    x,y=prepare(rows)
    scores=np.stack([runner.predict_tensor(a) for a in x])
    result={"at":now(),"split":split,"model_sha256":m["sha256"],"model_version":m["model_version"],"data_version":version,"manifest_sha256":data["files"][split]["sha256"],"metrics":metrics(y,scores),"predictions":[{"sample_id":r["sample_id"],"true_id":int(y[i]),"predicted_id":int(scores[i].argmax()),"confidence":float(scores[i].max())} for i,r in enumerate(rows)]}
    if split=="test":
        result["acceptance"]={"accuracy_passed":result["metrics"]["accuracy"]>=.85,"macro_f1_passed":result["metrics"]["macro_f1"]>=.8}
    out=ROOT/"experiments/reports/evaluations"/m["model_version"]/f"{version}-{split}.json"
    if out.exists():
        raise ValueError("Evaluation exists; preserve original final-test evidence")
    write_json(out,result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,8))
    matrix=np.array(result["metrics"]["confusion_matrix"])
    image=ax.imshow(matrix,cmap="Blues")
    names=runner.labels
    ax.set(xticks=range(10),yticks=range(10),xticklabels=names,yticklabels=names,xlabel="Predicted",ylabel="Actual",title=split)
    plt.setp(ax.get_xticklabels(),rotation=45,ha="right")
    for i in range(10):
        for j in range(10):
            ax.text(j,i,str(matrix[i,j]),ha="center",va="center",color="white" if matrix[i,j]>matrix.max()/2 else "black")
    fig.colorbar(image,ax=ax)
    fig.tight_layout();fig.savefig(out.with_suffix(".png"),dpi=160);plt.close(fig)
    from PIL import Image,ImageOps,ImageDraw
    wrong=[i for i in range(len(rows)) if int(scores[i].argmax())!=int(y[i])]
    result["error_sample_ids"]=[rows[i]["sample_id"] for i in wrong]
    write_json(out,result)
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
            draw.text((left+3,top+189),f"true={runner.labels[int(y[i])]} / pred={runner.labels[int(scores[i].argmax())]}",fill="black")
        sheet.save(out.with_name(out.stem+"-errors.png"))
    if split=="test":
        # Annex test evidence after model/threshold freeze; no selection changes.
        shutil.copyfile(out,release/"evaluation-test.json")
        shutil.copyfile(out.with_suffix(".png"),release/"confusion-matrix-test.png")
        m["acceptance"]["independent_field_accuracy"]={"accuracy":result["metrics"]["accuracy"],"macro_f1":result["metrics"]["macro_f1"],**result["acceptance"]}
        m["field_test"]={"data_version":version,"manifest_sha256":result["manifest_sha256"],"evaluated_at":result["at"]}
        write_json(release/"metadata.json",m)
        files=read_json(release/"release-files.json")
        for name in ("metadata.json","evaluation-test.json","confusion-matrix-test.png"):
            files[name]=digest(release/name)
        write_json(release/"release-files.json",files)
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
