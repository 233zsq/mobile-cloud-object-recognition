import json
from pathlib import Path
import numpy as np
import pytest
from recognition import common,training,release


def test_stage_order_and_shared_microtune_checkpoint(tmp_path,monkeypatch):
    monkeypatch.setattr(training,"ROOT",tmp_path)
    config={"learning_rate":.0003,"dropout":.2,"fine_tune_scope":"frozen","data_version":"v1","category_version":"campus-10-v1","batch_size":32,"seed":42,"augmentation":True,"max_epochs":20,"patience":3}
    path=tmp_path/"baseline.json";common.write_json(path,config)
    with pytest.raises(ValueError,match="Previous"):
        training.sweep(path,"campaign","dropout")
    prev=tmp_path/"previous.json"
    common.write_json(prev,{"stage":"dropout","winner":{"config":{**config,"learning_rate":.001,"dropout":.4},"checkpoint":"experiments/checkpoints/winner/best.keras"}})
    jobs_path=training.sweep(path,"campaign","fine_tune",prev)
    jobs=common.read_json(jobs_path)
    assert len(jobs["jobs"])==3
    assert len({j["initial_checkpoint"] for j in jobs["jobs"]})==1
    for j in jobs["jobs"]:
        candidate=common.read_json(tmp_path/j["config"])
        assert candidate["learning_rate"]==pytest.approx(.0001) and candidate["dropout"]==.4


def test_selector_uses_macro_f1_before_accuracy():
    a={"config":{"fine_tune_scope":"frozen"},"validation":{"macro_f1":.8,"accuracy":.9,"loss":.2}}
    b={"config":{"fine_tune_scope":"last_2"},"validation":{"macro_f1":.81,"accuracy":.85,"loss":.3}}
    assert training.rank(b)>training.rank(a)


def test_formal_export_refuses_smoke_before_loading_tensorflow(tmp_path):
    path=tmp_path/"result.json"
    common.write_json(path,{"status":"smoke"})
    with pytest.raises(ValueError,match="Formal package"):
        release.export(path,"invalid-formal",formal=True)


def test_normalized_input_is_not_silently_accepted():
    from recognition.inference import LiteRunner
    runner=LiteRunner.__new__(LiteRunner)
    with pytest.raises(ValueError,match="0..255"):
        runner.predict_tensor(np.full((224,224,3),-1,dtype=np.float32))


def test_deployment_refuses_unverified_package_before_loading_interpreter(tmp_path):
    from recognition.inference import LiteRunner
    common.write_json(tmp_path/'metadata.json',{'status':'verification_failed'})
    with pytest.raises(ValueError,match='not verified'):LiteRunner(tmp_path)


@pytest.mark.integration
def test_dropout_and_optimizer_continue_identically_after_checkpoint(tmp_path):
    import keras
    keras.utils.set_random_seed(42)
    model=keras.Sequential([
        keras.Input(shape=(8,)),
        keras.layers.Dense(16,activation='relu'),
        keras.layers.Dropout(.4,seed=42),
        keras.layers.Dense(10,activation='softmax'),
    ])
    model.compile(optimizer=keras.optimizers.Adam(.001),loss='sparse_categorical_crossentropy')
    x=np.random.default_rng(42).uniform(0,1,(4,8)).astype(np.float32)
    y=np.array([0,1,2,3])
    model.train_on_batch(x,y)
    state={'next_epoch':1}
    training.save_progress(model,tmp_path,state)
    restored=keras.models.load_model(tmp_path/state['resume_checkpoint'])
    training.restore_dropout_rng(restored,common.read_json(tmp_path/'state.json')['dropout_rng_state'])
    model.train_on_batch(x,y)
    restored.train_on_batch(x,y)
    assert training.dropout_rng_state(model)==training.dropout_rng_state(restored)
    for continuous,resumed in zip(model.weights,restored.weights):
        np.testing.assert_allclose(continuous.numpy(),resumed.numpy(),atol=1e-7,rtol=1e-6)
    for continuous,resumed in zip(model.optimizer.variables,restored.optimizer.variables):
        np.testing.assert_allclose(continuous.numpy(),resumed.numpy(),atol=1e-7,rtol=1e-6)


def test_resume_does_not_train_again_after_durable_early_stop(tmp_path,monkeypatch):
    import keras
    monkeypatch.setattr(training,'ROOT',tmp_path)
    config={'data_version':'v1','category_version':common.categories()['category_version'],
            'learning_rate':.001,'dropout':0,'batch_size':4,'max_epochs':20,'patience':3,
            'fine_tune_scope':'frozen','seed':42,'augmentation':False,'smoke':True,'pretrained_weights':None}
    path=tmp_path/'config.json';common.write_json(path,config)
    metadata={'category_version':config['category_version'],'purpose':'smoke'}
    dataset=tmp_path/'data/splits/v1/dataset.json';common.write_json(dataset,metadata)
    monkeypatch.setattr(training,'load_split',lambda *args:([{}],metadata))
    monkeypatch.setattr(training,'prepare',lambda rows:(np.zeros((1,224,224,3),np.float32),np.zeros(1,dtype=np.int32)))
    class FinishedModel:
        layers=[]
        def reset_metrics(self):
            raise AssertionError('Early-stopped run must not enter another epoch')
    monkeypatch.setattr(keras.models,'load_model',lambda path:FinishedModel())
    monkeypatch.setattr(training,'predict',lambda *args:np.full((1,10),.1,np.float32))
    monkeypatch.setattr(training,'plots',lambda *args:None)
    run=tmp_path/'experiments/checkpoints/early-stopped';run.mkdir(parents=True)
    (run/'latest.keras').write_bytes(b'last-complete-epoch')
    (run/'best.keras').write_bytes(b'best-complete-epoch')
    state={'identity':{'config':config,'data_metadata_sha256':common.digest(dataset),
                       'code_snapshot_sha256':training.snapshot(),'initial_checkpoint_sha256':None},
           'status':'running','next_epoch':1,'bad_epochs':3,'best_epoch':1,'dropout_rng_state':{},
           'environment':{},'code_commit':'test','started_at':'test','training_seconds':1,'history':[{'epoch':1}]}
    common.write_json(run/'state.json',state)
    result=training.train(path,'early-stopped',resume=True)
    assert len(result['history'])==1
    assert common.read_json(run/'state.json')['next_epoch']==1


@pytest.mark.parametrize('stage,actual,planned',[
    ('fine_tune','wrong','head.keras'),
    ('fine_tune',None,'head.keras'),
    ('learning_rate','unexpected',None),
    ('dropout','unexpected',None),
])
def test_summary_refuses_incompatible_initial_checkpoints(tmp_path,monkeypatch,stage,actual,planned):
    monkeypatch.setattr(training,'ROOT',tmp_path)
    monkeypatch.setattr(common,'ROOT',tmp_path)
    (tmp_path/'head.keras').write_bytes(b'planned-head')
    config={'fine_tune_scope':'frozen'}
    common.write_json(tmp_path/'config.json',config)
    common.write_json(tmp_path/'jobs.json',{'stage':stage,'campaign':'test','jobs':[
        {'experiment_id':'candidate','config':'config.json','initial_checkpoint':planned}]})
    common.write_json(tmp_path/'experiments/reports/candidate/result.json',{
        'status':'complete','config':config,'identity':{'initial_checkpoint_sha256':actual}})
    with pytest.raises(ValueError,match='initial checkpoint|fixed model initialization'):
        training.summarize(tmp_path/'jobs.json')


def test_summary_refuses_different_heads_even_when_each_job_hash_matches(tmp_path,monkeypatch):
    monkeypatch.setattr(training,'ROOT',tmp_path)
    monkeypatch.setattr(common,'ROOT',tmp_path)
    jobs=[]
    for i in range(2):
        checkpoint=tmp_path/f'head-{i}.keras';checkpoint.write_bytes(f'head-{i}'.encode())
        config={'fine_tune_scope':['frozen','last_1'][i]}
        common.write_json(tmp_path/f'config-{i}.json',config)
        job={'experiment_id':f'candidate-{i}','config':f'config-{i}.json','initial_checkpoint':checkpoint.name}
        jobs.append(job)
        common.write_json(tmp_path/'experiments/reports'/job['experiment_id']/'result.json',{
            'status':'complete','config':config,'environment':{},
            'identity':{'data_metadata_sha256':'same-data','code_snapshot_sha256':'same-code',
                        'initial_checkpoint_sha256':common.digest(checkpoint)}})
    common.write_json(tmp_path/'jobs.json',{'stage':'fine_tune','campaign':'test','jobs':jobs})
    with pytest.raises(ValueError,match='different initial classification head'):
        training.summarize(tmp_path/'jobs.json')
