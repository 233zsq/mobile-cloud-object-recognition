"""Deterministic epoch runner, stage selection, resumable checkpoints."""
import os
os.environ.setdefault("KERAS_HOME", str(__import__("pathlib").Path(__file__).resolve().parents[3]/"experiments/checkpoints/keras-cache"))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
import numpy as np
from .common import ROOT, TZ, categories, code_commit, digest, image_path, now, read_json, safe_name, write_csv, write_json
from .data import load_split
from .preprocessing import augment, preprocess


def metrics(labels,scores):
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    prediction=np.argmax(scores,axis=1)
    names=[c["label_key"] for c in categories()["categories"]]
    return {"accuracy":float(accuracy_score(labels,prediction)),"macro_f1":float(f1_score(labels,prediction,labels=list(range(10)),average="macro",zero_division=0)),"loss":float(-np.log(np.clip(scores[np.arange(len(labels)),labels],1e-8,1)).mean()),"classification_report":classification_report(labels,prediction,labels=list(range(10)),target_names=names,output_dict=True,zero_division=0),"confusion_matrix":confusion_matrix(labels,prediction,labels=list(range(10))).tolist(),"sample_count":len(labels)}


def prepare(rows):
    return np.stack([preprocess(image_path(r["image_path"])) for r in rows]),np.array([int(r["category_id"]) for r in rows],dtype=np.int32)


def predict(model,images,batch=32):
    return np.concatenate([np.asarray(model(images[i:i+batch],training=False)) for i in range(0,len(images),batch)])


def scope(model,name):
    import keras
    backbone=next(layer for layer in model.layers if isinstance(layer,keras.Model))
    if name not in ("frozen","last_1","last_2"):
        raise ValueError("Unknown fine tune scope")
    backbone.trainable=True
    for layer in backbone.layers:
        enabled=name!="frozen" and (layer.name=="Conv_1" or layer.name.startswith("block_16_") or (name=="last_2" and layer.name.startswith("block_15_")))
        layer.trainable=enabled and not isinstance(layer,keras.layers.BatchNormalization)
    return backbone


def build(config):
    import keras
    backbone=keras.applications.MobileNetV2(include_top=False,weights=config.get("pretrained_weights","imagenet"),alpha=1.0,input_shape=(224,224,3))
    inputs=keras.Input(shape=(224,224,3),dtype="float32",name="rgb_pixels")
    x=keras.layers.Rescaling(1/127.5,offset=-1,name="input_normalization")(inputs)
    x=backbone(x,training=False)
    x=keras.layers.GlobalAveragePooling2D()(x)
    x=keras.layers.Dropout(config["dropout"],seed=config["seed"])(x)
    outputs=keras.layers.Dense(10,activation="softmax",kernel_initializer=keras.initializers.GlorotUniform(seed=config["seed"]),name="class_scores")(x)
    model=keras.Model(inputs,outputs,name="campus_mobilenetv2")
    scope(model,config["fine_tune_scope"])
    return model


def rank(result):
    c=result["config"]
    m=result["validation"]
    return (m["macro_f1"],m["accuracy"],-m["loss"],-{"frozen":0,"last_1":1,"last_2":2}[c["fine_tune_scope"]])


def threshold(labels,scores):
    confidence=scores.max(axis=1)
    correct=scores.argmax(axis=1)==labels
    table=[]
    for t in np.arange(.5,.951,.05):
        mask=confidence>=t
        n=int(mask.sum())
        table.append({"threshold":round(float(t),2),"count":n,"coverage":float(mask.mean()),"accuracy":float(correct[mask].mean()) if n else None})
    eligible=[r for r in table if r["count"]>=30 and r["accuracy"]>=.9]
    best=max(eligible,key=lambda r:(r["coverage"],-r["threshold"])) if eligible else {"threshold":.6}
    return {"threshold":best["threshold"],"status":"validation_selected" if eligible else "provisional", "source":"validation only","candidates":table}


def snapshot():
    h=hashlib.sha256()
    for path in sorted(__import__("pathlib").Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def save_model(model,path):
    temp=path.with_name(path.stem+".tmp.keras")
    model.save(temp)
    temp.replace(path)


def save_progress(model, run, state):
    # Publish a new immutable model first, then atomically move the state pointer.
    # An interruption between the writes leaves the previous pair resumable.
    checkpoint=run/f"epoch-{state['next_epoch']:03}.keras"
    save_model(model,checkpoint)
    state['resume_checkpoint']=checkpoint.name
    state['resume_checkpoint_sha256']=digest(checkpoint)
    state['dropout_rng_state']=dropout_rng_state(model)
    write_json(run/'state.json',state)
    shutil.copyfile(checkpoint,run/'latest.keras')


def dropout_rng_state(model):
    import keras
    return {layer.name:layer.seed_generator.state.numpy().tolist()
            for layer in model.layers
            if isinstance(layer,keras.layers.Dropout) and layer.rate>0}


def restore_dropout_rng(model,states):
    import keras
    layers={layer.name:layer for layer in model.layers
            if isinstance(layer,keras.layers.Dropout) and layer.rate>0}
    if states is None or set(states)!=set(layers):
        raise ValueError('Resume Dropout random state is missing or differs')
    for name,layer in layers.items():
        value=np.asarray(states[name],dtype=np.int64)
        if value.shape!=tuple(layer.seed_generator.state.shape):
            raise ValueError('Resume Dropout random state shape differs')
        layer.seed_generator.state.assign(value)


def preflight(require_gpu=False):
    """Measure the common batch under frozen and largest fine-tuning scopes."""
    import keras
    import tensorflow as tf
    import tempfile
    from ai_edge_litert.interpreter import Interpreter
    gpus=tf.config.list_physical_devices("GPU")
    if require_gpu and not gpus:
        raise ValueError("GPU preflight requires a real TensorFlow GPU; CPU fallback is not GPU validation")
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu,True)
    directory=ROOT/"experiments/checkpoints/environment-preflight"
    directory.mkdir(parents=True,exist_ok=True)
    records=[]
    for batch in (32,16):
        records=[]
        try:
            for name in ("frozen","last_2"):
                keras.backend.clear_session()
                keras.utils.set_random_seed(42)
                if gpus:
                    tf.config.experimental.reset_memory_stats("GPU:0")
                model=build({"dropout":.2,"seed":42,"fine_tune_scope":name})
                model.compile(optimizer=keras.optimizers.Adam(.0003 if name=="frozen" else .00003),loss="sparse_categorical_crossentropy")
                x=np.random.default_rng(42).uniform(0,255,(batch,224,224,3)).astype(np.float32)
                y=np.arange(batch,dtype=np.int32)%10
                before=model.get_layer("class_scores").kernel.numpy().copy()
                began=time.perf_counter()
                loss=float(model.train_on_batch(x,y))
                if not np.isfinite(loss) or np.array_equal(before,model.get_layer("class_scores").kernel.numpy()):
                    raise ValueError("Preflight gradient did not update the classifier")
                record={"scope":name,"batch_size":batch,"gradient_updated":True,"loss":loss,"seconds":time.perf_counter()-began,"gpu_memory":tf.config.experimental.get_memory_info("GPU:0") if gpus else None}
                records.append(record)
            save_model(model,directory/"latest.keras")
            restored=keras.models.load_model(directory/"latest.keras")
            if int(restored.optimizer.iterations)!=1:
                raise ValueError("Preflight optimizer state failed to restore")
            with tempfile.TemporaryDirectory(prefix="campus-preflight-") as staging:
                restored.export(staging,input_signature=[tf.TensorSpec([1,224,224,3],tf.float32)],verbose=False)
                converter=tf.lite.TFLiteConverter.from_saved_model(staging)
                converter.target_spec.supported_ops=[tf.lite.OpsSet.TFLITE_BUILTINS]
                converter.optimizations=[]
                blob=converter.convert()
            (directory/"model.tflite").write_bytes(blob)
            interpreter=Interpreter(model_content=blob,num_threads=1);interpreter.allocate_tensors()
            inp,out=interpreter.get_input_details()[0],interpreter.get_output_details()[0]
            if inp["dtype"]!=np.float32 or out["dtype"]!=np.float32 or list(inp["shape"])!=[1,224,224,3] or list(out["shape"])!=[1,10]:
                raise ValueError("Preflight tensor contract differs")
            interpreter.set_tensor(inp["index"],x[:1]);interpreter.invoke()
            delta=float(np.max(np.abs(interpreter.get_tensor(out["index"])-restored(x[:1],training=False).numpy())))
            if delta>.001:
                raise ValueError("Preflight Keras/LiteRT mismatch")
            result={"at":now(),"status":"gpu_passed" if gpus else "cpu_only_gpu_pending","recommended_common_batch":batch,"device":[p.name for p in gpus] or ["CPU"],"checks":records,"optimizer_restored":True,"fp32_builtin_conversion_passed":True,"max_score_difference":delta,"code_snapshot_sha256":snapshot()}
            write_json(ROOT/"experiments/reports/environment/preflight.json",result)
            return result
        except tf.errors.ResourceExhaustedError:
            keras.backend.clear_session()
            if batch==16:
                raise
    raise RuntimeError("No common batch succeeded")


def train(config_path,experiment_id,resume=False,initial_checkpoint=None):
    import tensorflow as tf
    import keras
    config=read_json(config_path)
    safe_name(experiment_id)
    if config.get("category_version")!=categories(config.get("category_version"))["category_version"]:
        raise ValueError("Config category version mismatch")
    if config.get("architecture","MobileNetV2")!="MobileNetV2" or config.get("alpha",1.0)!=1.0 or config.get("num_classes",10)!=10 or config.get("input_shape",[224,224,3])!=[224,224,3]:
        raise ValueError("Architecture/input/class dimensions differ from fixed MobileNetV2 contract")
    if not config.get("smoke") and config.get("pretrained_weights","imagenet")!="imagenet":
        raise ValueError("Formal training requires ImageNet pretrained weights")
    if config.get("fine_tune_scope") not in ("frozen","last_1","last_2") or not 0<=config["dropout"]<1:
        raise ValueError("Invalid training configuration")
    if config["batch_size"] not in (16,32) and not config.get("smoke"):
        raise ValueError("Formal batch size must be consistently 16 or 32")
    if not 1<=config["max_epochs"]<=20 or config["learning_rate"]<=0:
        raise ValueError("Invalid epoch/lr budget")
    if not config.get("smoke") and not config.get("augmentation"):
        raise ValueError("Formal training requires the fixed augmentation contract")
    for gpu in tf.config.list_physical_devices("GPU"):
        tf.config.experimental.set_memory_growth(gpu,True)
    keras.utils.set_random_seed(config["seed"])
    tf.config.experimental.enable_op_determinism()
    run=ROOT/"experiments/checkpoints"/experiment_id
    if run.exists() and not resume:
        raise ValueError("Run ID exists; use --resume or a new ID")
    rows,data=load_split(config["data_version"],"train")
    if data["category_version"]!=config["category_version"]:
        raise ValueError("Config category version differs from frozen data")
    valrows,_=load_split(config["data_version"],"validation")
    x,y=prepare(rows)
    vx,vy=prepare(valrows)
    if data.get("purpose")=="smoke" and not config.get("smoke"):
        raise ValueError("Smoke fixtures cannot be used for formal training")
    identity={"config":config,"data_metadata_sha256":digest(ROOT/"data/splits"/config["data_version"]/"dataset.json"),"code_snapshot_sha256":snapshot(),"initial_checkpoint_sha256":digest(initial_checkpoint) if initial_checkpoint else None}
    state_path=run/"state.json"
    result_path=ROOT/"experiments/reports"/experiment_id/"result.json"
    if resume:
        state=read_json(state_path)
        if state["identity"]!=identity:
            raise ValueError("Resume config/data/code/initial checkpoint differs from saved run")
        if state["status"]=="complete" and result_path.exists():
            return read_json(result_path)
        checkpoint=run/state.get("resume_checkpoint","latest.keras")
        if state.get("resume_checkpoint_sha256") and digest(checkpoint)!=state["resume_checkpoint_sha256"]:
            raise ValueError("Resume checkpoint hash changed")
        model=keras.models.load_model(checkpoint)
        restore_dropout_rng(model,state.get('dropout_rng_state'))
    else:
        run.mkdir(parents=True,exist_ok=True)
        source_dir=run/"code-snapshot/recognition"
        source_dir.mkdir(parents=True,exist_ok=True)
        for source in __import__("pathlib").Path(__file__).parent.glob("*.py"):
            shutil.copyfile(source,source_dir/source.name)
        installed=subprocess.check_output([sys.executable,"-m","pip","freeze","--exclude-editable"],text=True)
        (run/"installed-dependencies.lock").write_text(installed,encoding="utf-8")
        if initial_checkpoint:
            model=keras.models.load_model(initial_checkpoint)
            dropout=next(layer for layer in model.layers if isinstance(layer,keras.layers.Dropout))
            if dropout.rate!=config["dropout"]:
                raise ValueError("Initial head checkpoint Dropout differs from candidate config")
            scope(model,config["fine_tune_scope"])
        else:
            model=build(config)
        model.compile(optimizer=keras.optimizers.Adam(config["learning_rate"]),loss="sparse_categorical_crossentropy")
        state={"identity":identity,"next_epoch":0,"best":None,"best_loss":float("inf"),"bad_epochs":0,"history":[],"started_at":now(),"code_commit":code_commit(),"environment":{"python":platform.python_version(),"tensorflow":tf.__version__,"keras":keras.__version__,"gpu":[g.name for g in tf.config.list_physical_devices("GPU")],"platform":platform.platform(),"dependencies_sha256":digest(run/"installed-dependencies.lock")},"status":"running","training_seconds":0}
        save_progress(model,run,state)
    epochs=range(state["next_epoch"],config["max_epochs"])
    if state['status'] in ('finalizing','complete') or state['bad_epochs']>=config.get('patience',3):
        epochs=()
    for epoch in epochs:
        local=datetime.now(TZ)
        deadline=local.replace(hour=config.get("stop_hour",23),minute=0,second=0,microsecond=0)
        estimate=max([r["seconds"] for r in state["history"][-3:]] or [60])+15
        if local.hour>=config.get("stop_hour",23) or local.hour<6 or (deadline-local).total_seconds()<estimate:
            state["status"]="paused_time_window"
            if not (run/"latest.keras").exists():
                save_model(model,run/"latest.keras")
            write_json(state_path,state)
            return state
        began=time.perf_counter()
        rng=np.random.default_rng(np.random.SeedSequence([config["seed"],epoch]))
        order=rng.permutation(len(x))
        model.reset_metrics()
        losses=[]
        for i in range(0,len(x),config["batch_size"]):
            indices=order[i:i+config["batch_size"]]
            images=np.stack([augment(x[j],np.random.default_rng(np.random.SeedSequence([config["seed"],epoch,int(j)]))) for j in indices]) if config.get("augmentation") else x[indices]
            losses.append(float(model.train_on_batch(images,y[indices])))
        scores=predict(model,vx,config["batch_size"])
        result=metrics(vy,scores)
        elapsed=time.perf_counter()-began
        state["training_seconds"]+=elapsed
        entry={"epoch":epoch+1,"training_loss":losses[-1],"validation_accuracy":result["accuracy"],"validation_macro_f1":result["macro_f1"],"validation_loss":result["loss"],"seconds":elapsed}
        state["history"].append(entry)
        candidate={"config":config,"validation":result}
        if state["best"] is None or rank(candidate)>rank({"config":config,"validation":state["best"]}):
            state["best"]=result
            state["best_epoch"]=epoch+1
            save_model(model,run/"best.keras")
        if result["loss"]<state["best_loss"]:
            state["best_loss"]=result["loss"]
            state["bad_epochs"]=0
        else:
            state["bad_epochs"]+=1
        state["next_epoch"]=epoch+1
        save_progress(model,run,state)
        print(experiment_id,entry,flush=True)
        if state["bad_epochs"]>=config.get("patience",3):
            break
    state["status"]="finalizing"
    write_json(state_path,state)
    best=keras.models.load_model(run/"best.keras")
    scores=predict(best,vx,config["batch_size"])
    result={"experiment_id":experiment_id,"status":"smoke" if config.get("smoke") else "complete","config":config,"identity":identity,"validation":metrics(vy,scores),"threshold":threshold(vy,scores),"best_epoch":state["best_epoch"],"checkpoint":str((run/"best.keras").relative_to(ROOT)),"checkpoint_sha256":digest(run/"best.keras"),"environment":state["environment"],"code_commit":state["code_commit"],"started_at":state["started_at"],"training_seconds":state["training_seconds"],"history":state["history"]}
    plots(result,ROOT/"experiments/reports"/experiment_id)
    write_json(result_path,result)
    state["status"]="complete"
    write_json(state_path,state)
    return result


def plots(result,directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    directory.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    fig.suptitle("SYNTHETIC SMOKE - not object accuracy" if result["status"]=="smoke" else result["experiment_id"])
    h=result["history"]
    axes[0].plot([x["epoch"] for x in h],[x["training_loss"] for x in h],label="training")
    axes[0].plot([x["epoch"] for x in h],[x["validation_loss"] for x in h],label="validation")
    axes[0].set(xlabel="Epoch",ylabel="Cross entropy")
    axes[0].legend()
    axes[1].plot([x["epoch"] for x in h],[x["validation_accuracy"] for x in h],label="accuracy")
    axes[1].plot([x["epoch"] for x in h],[x["validation_macro_f1"] for x in h],label="macro F1")
    axes[1].set(xlabel="Epoch",ylabel="Validation score",ylim=(0,1))
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(directory/"training-curves.png",dpi=160)
    plt.close(fig)


def sweep(base_path,campaign,stage,previous=None,execute=False):
    safe_name(campaign)
    base=read_json(base_path)
    if stage not in ("learning_rate","dropout","fine_tune"):
        raise ValueError("Unknown stage")
    if stage!="learning_rate" and not previous:
        raise ValueError("Previous stage summary required")
    parent=read_json(previous) if previous else None
    expected={"dropout":"learning_rate","fine_tune":"dropout"}
    if parent and parent["stage"]!=expected[stage]:
        raise ValueError("Stages must follow learning rate -> dropout -> fine tune")
    if parent:
        old=parent["winner"]["config"]
        for key in ("data_version","category_version","batch_size","seed","augmentation","max_epochs","patience"):
            if base.get(key)!=old.get(key):
                raise ValueError("Candidate data/environment protocol differs from prior stage")
        base["learning_rate"]=old["learning_rate"]
        if stage=="fine_tune":
            base["dropout"]=old["dropout"]
            base["learning_rate"]*=.1
    values={"learning_rate":[.0001,.0003,.001],"dropout":[0,.2,.4],"fine_tune":["frozen","last_1","last_2"]}[stage]
    jobs=[]
    proposed={}
    for index,value in enumerate(values):
        config=dict(base)
        config["fine_tune_scope"]="frozen"
        config["fine_tune_scope" if stage=="fine_tune" else stage]=value
        if stage=="learning_rate":
            config["dropout"]=.2
        experiment=f"{campaign}-{stage}-{index+1}"
        path=ROOT/"ml/configs/generated"/campaign/f"{experiment}.json"
        proposed[path]=config
        jobs.append({"experiment_id":experiment,"config":path.relative_to(ROOT).as_posix(),"pc_slot":index+1,"initial_checkpoint":parent["winner"]["checkpoint"] if stage=="fine_tune" else None})
    plan={"campaign":campaign,"stage":stage,"jobs":jobs,"pc_4":"reproduction/development; does not share GPU memory","previous_summary":str(previous) if previous else None}
    plan_path=ROOT/"experiments/reports"/campaign/f"{stage}-jobs.json"
    proposed[plan_path]=plan
    for job in jobs:
        command=["python","-m","recognition","train","--config",job["config"],"--experiment",job["experiment_id"]]
        if job["initial_checkpoint"]:
            command.extend(["--initial-checkpoint",job["initial_checkpoint"]])
        config_path=ROOT/job['config']
        # Match write_json's UTF-8/platform newline bytes for a new file;
        # keep the original bytes/hash when the same JSON already exists.
        encoded=(json.dumps(proposed[config_path],ensure_ascii=False,indent=2)+'\n').replace('\n',os.linesep).encode('utf-8')
        config_hash=digest(config_path) if config_path.exists() else hashlib.sha256(encoded).hexdigest()
        proposed[plan_path.parent/"pc-tasks"/f"{stage}-pc{job['pc_slot']}.json"]={"pc_slot":job["pc_slot"],"data_version":base["data_version"],"category_version":base["category_version"],"config_sha256":config_hash,"command":command,"job":job}
    proposed[plan_path.parent/"pc-tasks"/f"{stage}-pc4.json"]={"pc_slot":4,"task":"reproduce selected complete head and fine-tune procedure with seed43","status":"waiting_for_primary_selection","data_version":base["data_version"],"category_version":base["category_version"],"command_template":["python","-m","recognition","reproduce","--result","<selected-result.json>","--seed","43"],"must_match":"same frozen data, source snapshot, Python and installed dependencies"}
    # Validate the whole campaign before the first mutation, even for jobs-only
    # export. A late conflict must not change earlier configs or resume evidence.
    for path,value in proposed.items():
        if path.exists() and read_json(path)!=value:
            raise ValueError('Existing campaign file differs; use a new campaign: '+str(path))
    for job in jobs:
        config=proposed[ROOT/job['config']]
        run=ROOT/'experiments/checkpoints'/job['experiment_id']
        result=ROOT/'experiments/reports'/job['experiment_id']/'result.json'
        state=run/'state.json'
        if run.exists() and not state.exists() and not result.exists():
            raise ValueError('Existing candidate has no resumable state; use a new campaign')
        for saved in (result,state):
            if not saved.exists():
                continue
            old=read_json(saved)
            identity=old['identity']
            if identity['config']!=config or old.get('config',config)!=config or identity['code_snapshot_sha256']!=snapshot() or identity['data_metadata_sha256']!=digest(ROOT/'data/splits'/config['data_version']/'dataset.json'):
                raise ValueError('Existing candidate config/code/data differs; use a new campaign')
            validate_initial_checkpoint(old,job,stage)
    for path,value in proposed.items():
        if not path.exists():
            write_json(path,value)
    if execute:
        for job in jobs:
            finished=ROOT/"experiments/reports"/job["experiment_id"]/"result.json"
            if finished.exists():
                continue
            resume=(ROOT/"experiments/checkpoints"/job["experiment_id"]/"state.json").exists()
            result=train(ROOT/job["config"],job["experiment_id"],resume=resume,initial_checkpoint=ROOT/job["initial_checkpoint"] if job["initial_checkpoint"] else None)
            if result.get("status")=="paused_time_window":
                break
    return plan_path


def validate_initial_checkpoint(result,job,stage):
    initial=job.get('initial_checkpoint')
    actual=result['identity'].get('initial_checkpoint_sha256')
    if stage=='fine_tune':
        if not initial or not actual or actual!=digest(image_path(initial)):
            raise ValueError('Fine-tune initial checkpoint differs from the planned classification head')
    elif initial or actual is not None:
        raise ValueError('Learning-rate/Dropout candidates must start from the fixed model initialization')
    return actual


def summarize(jobs_path):
    jobs=read_json(jobs_path)
    results=[]
    for job in jobs["jobs"]:
        result=read_json(ROOT/"experiments/reports"/job["experiment_id"]/"result.json")
        if result["status"]!="complete" or result["config"]!=read_json(ROOT/job["config"]):
            raise ValueError("Missing/formally incomparable candidate result")
        initial_hash=validate_initial_checkpoint(result,job,jobs['stage'])
        if results and initial_hash!=results[0]['identity'].get('initial_checkpoint_sha256'):
            raise ValueError('Candidates use different initial classification head checkpoints')
        if results and (result["identity"]["data_metadata_sha256"]!=results[0]["identity"]["data_metadata_sha256"] or result["identity"]["code_snapshot_sha256"]!=results[0]["identity"]["code_snapshot_sha256"] or {k:v for k,v in result["environment"].items() if k!="platform"}!={k:v for k,v in results[0]["environment"].items() if k!="platform"}):
            raise ValueError("Candidates use different data/code/runtime")
        results.append(result)
    winner=max(results,key=rank)
    out=ROOT/"experiments/reports"/jobs["campaign"]/f"{jobs['stage']}-summary.json"
    write_json(out,{"stage":jobs["stage"],"winner":winner,"candidates":results})
    fields=["experiment_id","stage","pc_id","started_at","code_commit","data_version","category_version","seed","learning_rate","dropout","batch_size","fine_tune_scope","epochs","validation_accuracy","validation_macro_f1","training_seconds","checkpoint_path","notes"]
    table=[]
    for r in results:
        row={k:r["config"].get(k,"") for k in fields}
        row.update(experiment_id=r["experiment_id"],stage=jobs["stage"],pc_id=r["environment"]["platform"],started_at=r.get("started_at",""),code_commit=r["code_commit"],epochs=len(r["history"]),validation_accuracy=r["validation"]["accuracy"],validation_macro_f1=r["validation"]["macro_f1"],training_seconds=r["training_seconds"],checkpoint_path=r["checkpoint"])
        table.append(row)
    write_csv(out.with_suffix(".csv"),table,fields)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    field="fine_tune_scope" if jobs["stage"]=="fine_tune" else jobs["stage"]
    x=[r["config"][field] for r in results]
    fig,ax=plt.subplots(figsize=(7,4))
    ax.plot(x,[r["validation"]["macro_f1"] for r in results],"o-",label="validation macro F1")
    ax.plot(x,[r["validation"]["accuracy"] for r in results],"s--",label="validation accuracy")
    if field=="learning_rate":
        ax.set_xscale("log")
    ax.set(xlabel=field,ylabel="Validation score",ylim=(0,1),title=jobs["campaign"]+" / "+jobs["stage"])
    ax.legend();fig.tight_layout();fig.savefig(out.with_suffix(".png"),dpi=160);plt.close(fig)
    return out


def reproduce(result_path,seed=43):
    """Repeat the complete selected head + optional fine-tune procedure."""
    primary=read_json(result_path)
    if primary["status"]!="complete" or seed not in (43,44):
        raise ValueError("Formal primary and seed43/44 required")
    final=dict(primary["config"])
    final["seed"]=seed
    name=f"{primary['experiment_id']}-repeat{seed}"
    initial=None
    if final["fine_tune_scope"]!="frozen" or primary["identity"].get("initial_checkpoint_sha256"):
        head=dict(final)
        head.update(fine_tune_scope="frozen",learning_rate=final["learning_rate"]*10)
        head_id=name+"-head"
        path=ROOT/"ml/configs/generated"/(head_id+".json")
        write_json(path,head)
        completed=ROOT/"experiments/reports"/head_id/"result.json"
        if completed.exists():
            head_result=read_json(completed)
        else:
            head_result=train(path,head_id,resume=(ROOT/"experiments/checkpoints"/head_id/"state.json").exists())
        if head_result.get("status")=="paused_time_window":
            return head_result
        initial=ROOT/head_result["checkpoint"]
    path=ROOT/"ml/configs/generated"/(name+".json")
    write_json(path,final)
    result=train(path,name,resume=(ROOT/"experiments/checkpoints"/name/"state.json").exists(),initial_checkpoint=initial)
    if result.get("status")=="paused_time_window":
        return result
    difference=abs(primary["validation"]["macro_f1"]-result["validation"]["macro_f1"])
    write_json(ROOT/"experiments/reports"/name/"reproduction.json",{"primary":primary["experiment_id"],"repeat":name,"seed":seed,"macro_f1_difference":difference,"needs_seed44":seed==43 and difference>.05,"test_data_used":False})
    return result
