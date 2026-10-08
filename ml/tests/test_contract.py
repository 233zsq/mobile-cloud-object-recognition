import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from recognition import common, data
from recognition.preprocessing import bilinear, preprocess
from recognition.training import threshold


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    original=common.categories()
    monkeypatch.setattr(common,"ROOT",tmp_path)
    monkeypatch.setattr(data,"ROOT",tmp_path)
    common.write_json(tmp_path/"shared/categories.json",original)
    rows=[]
    rng=np.random.default_rng(123)
    for c in range(10):
        for i in range(4):
            path=tmp_path/f"data/raw/c{c}-{i}.png"
            path.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(rng.integers(0,256,(150,200,3),dtype=np.uint8)).save(path)
            row={k:"" for k in common.FIELDS}
            row.update(sample_id=f"c{c}-{i}",image_path=path.relative_to(tmp_path).as_posix(),image_sha256=common.digest(path),category_id=str(c),group_id=f"c{c}-g{i//2}",review_status="approved")
            rows.append(row)
    manifest=tmp_path/"data/manifests/samples.csv"
    common.write_csv(manifest,rows)
    return tmp_path,manifest,rows


def test_letterbox_preserves_long_subject_and_padding(tmp_path):
    path=tmp_path/"long.png"
    Image.new("RGB",(400,100),(12,34,56)).save(path)
    actual=preprocess(path)
    assert actual.shape==(224,224,3) and actual.dtype==np.float32
    assert np.all(actual[:84]==128) and np.all(actual[140:]==128)
    np.testing.assert_allclose(actual[84:140],np.broadcast_to([12,34,56],(56,224,3)),atol=1e-4)


def test_bilinear_half_pixel_reference():
    array=np.array([[[0]*3, [100]*3],[[200]*3,[255]*3]],dtype=np.float32)
    actual=bilinear(array,1,1)
    np.testing.assert_allclose(actual,[[(138.75,)*3]],atol=1e-6)


def test_exif_orientation(tmp_path):
    path=tmp_path/"rotated.jpg"
    im=Image.new("RGB",(300,100),"red")
    exif=Image.Exif();exif[274]=6
    im.save(path,exif=exif)
    actual=preprocess(path)
    assert np.all(actual[:,:74]==128) and actual[10,112,0]>200


def test_split_keeps_objects_together_and_freezes(workspace):
    root,manifest,rows=workspace
    meta=data.freeze_split(manifest,"v1")
    train,_=data.load_split("v1","train")
    val,_=data.load_split("v1","validation")
    assert {r["group_id"] for r in train}.isdisjoint(r["group_id"] for r in val)
    assert len(train)+len(val)==40 and set(meta["files"])=={"train","validation"}
    with pytest.raises(ValueError,match="exists"):
        data.freeze_split(manifest,"v1")
    with pytest.raises(ValueError,match="cannot read"):
        data.load_split("v1","test")


def test_changed_manifest_or_image_is_rejected(workspace):
    root,manifest,rows=workspace
    data.freeze_split(manifest,"v1")
    path=root/"data/splits/v1/train.csv"
    original=path.read_bytes()
    path.write_bytes(original+b"\n")
    with pytest.raises(ValueError,match="changed frozen"):
        data.load_split("v1","train")
    path.write_bytes(original)
    row=common.read_csv(path)[0]
    (root/row["image_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError,match="image bytes changed"):
        data.load_split("v1","train")


def test_frozen_category_archive_remains_reproducible(workspace):
    root,manifest,rows=workspace
    data.freeze_split(manifest,'archive-check')
    original=common.categories()
    import shutil
    archive=root/'shared/category-versions'/f"{original['category_version']}.json"
    archive.parent.mkdir(parents=True)
    shutil.copyfile(root/'shared/categories.json',archive)
    updated=dict(original,category_version='new-category-v3')
    common.write_json(root/'shared/categories.json',updated)
    assert len(data.load_split('archive-check','train')[0])>0


def test_exact_and_near_duplicates_cannot_cross_split():
    a={"sample_id":"a","image_sha256":"shared"}
    b={"sample_id":"b","image_sha256":"shared"}
    with pytest.raises(ValueError,match="leakage"):
        data.check_isolation([a],[b])
    with pytest.raises(ValueError,match="near duplicate"):
        data.check_isolation([{"phash":"0000000000000000"}],[{"phash":"0000000000000001"}])


def test_source_path_cannot_escape_repo(workspace):
    with pytest.raises(ValueError,match="inside repository"):
        common.image_path("../outside.png")


def test_unknown_review_sample_is_rejected(workspace):
    root,manifest,rows=workspace
    decisions=root/"decisions.csv"
    common.write_csv(decisions,[{"sample_id":"mistyped-id","review_status":"approved"}],fields=["sample_id","review_status"])
    with pytest.raises(ValueError,match="unknown samples"):
        data.audit(manifest,decisions,contact_sheets=False)


def test_exact_duplicates_are_removed_from_approved_counts(workspace):
    root,manifest,rows=workspace
    rows[1].update(image_path=rows[0]['image_path'],image_sha256=rows[0]['image_sha256'])
    common.write_csv(manifest,rows)
    with pytest.raises(ValueError,match='Exact duplicates'):
        data.freeze_split(manifest,'bad-duplicate')
    reviewed=data.audit(manifest,contact_sheets=False)
    assert reviewed[0]['review_status']=='approved'
    assert reviewed[1]['review_status']=='rejected'
    assert reviewed[1]['review_reason']=='exact_duplicate_of:'+rows[0]['sample_id']


def test_audit_never_auto_approves(workspace):
    root,manifest,rows=workspace
    for r in rows:
        r["review_status"]="pending"
    common.write_csv(manifest,rows)
    audited=data.audit(manifest,contact_sheets=False)
    assert not any(r["review_status"]=="approved" for r in audited)


def test_low_confidence_threshold_is_supported_by_validation_count():
    labels=np.zeros(40,dtype=int)
    scores=np.zeros((40,10),np.float32)
    scores[:,0]=.8;scores[:,1]=.2
    chosen=threshold(labels,scores)
    assert chosen["status"]=="validation_selected" and chosen["threshold"]==.5
    assert threshold(labels[:20],scores[:20])["status"]=="provisional"


def test_formal_test_refuses_public_photos(workspace):
    root,manifest,rows=workspace
    data.freeze_split(manifest,"train-v1")
    with pytest.raises(ValueError,match="field photos"):
        data.freeze_field_test(manifest,"test-v1","train-v1")


def test_transparency_uses_grey_background(tmp_path):
    path=tmp_path/"transparent.png"
    Image.new("RGBA",(224,224),(255,0,0,0)).save(path)
    assert np.all(preprocess(path)==128)


@pytest.mark.integration
def test_paused_run_can_resume_and_optimizer_state_is_restored(workspace,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from recognition import training
    root,manifest,rows=workspace
    monkeypatch.setattr(training,"ROOT",root)
    data.freeze_split(manifest,"v1")
    tz=timezone(timedelta(hours=8))
    class Clock:
        hour=23
        @classmethod
        def now(cls,tz):
            return datetime(2026,10,7,cls.hour,0,tzinfo=tz)
    monkeypatch.setattr(training,"datetime",Clock)
    config={"data_version":"v1","category_version":common.categories()["category_version"],"learning_rate":.0003,"dropout":.2,"batch_size":4,"max_epochs":1,"patience":3,"fine_tune_scope":"frozen","seed":42,"stop_hour":23,"augmentation":False,"smoke":True,"pretrained_weights":None}
    path=root/"config.json";common.write_json(path,config)
    paused=training.train(path,"resume-check")
    assert paused["status"]=="paused_time_window" and paused["next_epoch"]==0
    Clock.hour=8
    original_plots=training.plots
    def interrupt_curve_publication(*args):
        raise OSError('simulated interruption before curve publication')
    monkeypatch.setattr(training,'plots',interrupt_curve_publication)
    with pytest.raises(OSError,match='before curve publication'):
        training.train(path,'resume-check',resume=True)
    assert not (root/'experiments/reports/resume-check/result.json').exists()
    assert common.read_json(root/'experiments/checkpoints/resume-check/state.json')['status']=='finalizing'
    monkeypatch.setattr(training,'plots',original_plots)
    original_write=training.write_json
    def interrupt_final_evaluation(path,value):
        if Path(path).name=='result.json':
            raise OSError('simulated interruption before result publication')
        original_write(path,value)
    monkeypatch.setattr(training,'write_json',interrupt_final_evaluation)
    with pytest.raises(OSError,match='before result publication'):
        training.train(path,"resume-check",resume=True)
    interrupted=common.read_json(root/'experiments/checkpoints/resume-check/state.json')
    assert interrupted['status']=='finalizing' and interrupted['next_epoch']==1
    import keras
    latest=keras.models.load_model(root/"experiments/checkpoints/resume-check/latest.keras")
    interrupted_iterations=int(latest.optimizer.iterations)
    monkeypatch.setattr(training,'write_json',original_write)
    completed=training.train(path,"resume-check",resume=True)
    assert completed["status"]=="smoke" and len(completed["history"])==1
    state=common.read_json(root/'experiments/checkpoints/resume-check/state.json')
    assert state['resume_checkpoint_sha256']==common.digest(root/'experiments/checkpoints/resume-check'/state['resume_checkpoint'])
    latest=keras.models.load_model(root/"experiments/checkpoints/resume-check/latest.keras")
    assert int(latest.optimizer.iterations)>0
    assert int(latest.optimizer.iterations)==interrupted_iterations
    iterations=int(latest.optimizer.iterations)
    again=training.train(path,"resume-check",resume=True)
    latest=keras.models.load_model(root/"experiments/checkpoints/resume-check/latest.keras")
    assert int(latest.optimizer.iterations)==iterations
    assert completed["checkpoint_sha256"]==again["checkpoint_sha256"]
    # Repair a completed state whose result was never durably published.
    (root/'experiments/reports/resume-check/result.json').unlink()
    recovered=training.train(path,'resume-check',resume=True)
    assert recovered['checkpoint_sha256']==completed['checkpoint_sha256']
    assert common.read_json(root/'experiments/checkpoints/resume-check/state.json')['status']=='complete'
