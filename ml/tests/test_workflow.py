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
