import numpy as np
import pytest
from recognition import common,release,data
from recognition.preprocessing import SPEC
from PIL import Image


def test_external_reference_scores_and_hashes_are_checked(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    bundle=tmp_path/'model'
    common.write_json(bundle/'metadata.json',{'sha256':'model','labels_sha256':'labels','input':SPEC,'model_version':'v1'})
    scores=[1.0]+[0.0]*9
    common.write_json(bundle/'examples/manifest.json',[{'sample_id':'cup','tensor_sha256':'tensor','scores':scores,'predicted_id':0}])
    report={'run_id':'device-one','device':'test device','runtime':'test runtime','mode':'reference_tensor','model_sha256':'model','labels_sha256':'labels','input_contract':SPEC,'samples':[{'sample_id':'cup','tensor_sha256':'tensor','scores':scores}]}
    path=tmp_path/'report.json';common.write_json(path,report)
    assert release.compare_external(bundle,path)['passed']
    report['run_id']='wrong-scores';report['samples'][0]['scores']=[0.0,1.0]+[0.0]*8
    common.write_json(path,report)
    with pytest.raises(ValueError,match='differences failed'):release.compare_external(bundle,path)
    assert not common.read_json(tmp_path/'experiments/reports/consistency/v1/wrong-scores.json')['passed']
    report['model_sha256']='wrong';common.write_json(path,report)
    with pytest.raises(ValueError,match='SHA-256'):release.compare_external(bundle,path)


def test_external_image_chain_rejects_repeated_normalization(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    bundle=tmp_path/'model'; scores=[1.0]+[0.0]*9
    common.write_json(bundle/'metadata.json',{'sha256':'model','labels_sha256':'labels','input':SPEC,'model_version':'v1'})
    (bundle/'examples').mkdir(exist_ok=True)
    reference=bundle/'examples/input.bin';np.full((224,224,3),128,dtype='<f4').tofile(reference)
    common.write_json(bundle/'examples/manifest.json',[{'sample_id':'cup','tensor':'input.bin','tensor_sha256':common.digest(reference),'scores':scores,'predicted_id':0}])
    actual=tmp_path/'actual.bin';np.full((224,224,3),128/255,dtype='<f4').tofile(actual)
    report={'run_id':'normalized-image','device':'test device','runtime':'test runtime','mode':'image_chain','model_sha256':'model','labels_sha256':'labels','input_contract':SPEC,'samples':[{'sample_id':'cup','tensor_file':'actual.bin','scores':scores}]}
    path=tmp_path/'report.json';common.write_json(path,report)
    with pytest.raises(ValueError,match='differences failed'):release.compare_external(bundle,path)
    result=common.read_json(tmp_path/'experiments/reports/consistency/v1/normalized-image.json')
    assert result['comparisons'][0]['max_input_difference']>127


def test_field_freeze_refuses_duplicate_images_before_reading_test_files():
    rows=[{'sample_id':f'{c}-{i}','image_sha256':f'{c}-{i}','category_id':str(c),'object_id':f'o{c}-{i//4}','session_id':'session','source_dataset':'field','review_status':'approved'} for c in range(10) for i in range(20)]
    data.validate_field_rows(rows)
    rows[1]['image_sha256']=rows[0]['image_sha256']
    with pytest.raises(ValueError,match='Duplicate field'):data.validate_field_rows(rows)


@pytest.mark.parametrize('version,manifest_sha256',[
    ('field-v1','manifest'),('renamed-field-version','manifest'),('field-v1','different-manifest')])
def test_changed_model_requires_unused_independent_test_version(tmp_path,monkeypatch,version,manifest_sha256):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    common.write_json(tmp_path/'experiments/reports/evaluations/model-v1/field-v1-test.json',{
        'split':'test','data_version':'field-v1','manifest_sha256':'manifest','model_sha256':'model-one',
        'image_sha256s':['used-photo']})
    fresh=[{'image_sha256':'fresh-photo'}]
    with pytest.raises(ValueError,match='different model'):
        release.check_test_model_binding(version,manifest_sha256,'model-two',fresh)
    release.check_test_model_binding('field-v1','manifest','model-one',fresh)
    release.check_test_model_binding('field-v2','new-manifest','model-two',fresh)


def test_renamed_and_refrozen_field_photos_cannot_be_evaluated_by_another_model(tmp_path,monkeypatch):
    for module in (common,data,release):
        monkeypatch.setattr(module,'ROOT',tmp_path)
    repo=__import__('pathlib').Path(__file__).resolve().parents[2]
    common.write_json(tmp_path/'shared/categories.json',common.read_json(repo/'shared/categories.json'))
    def samples(prefix,count,field):
        rows=[]
        for category in range(10):
            for index in range(count):
                path=tmp_path/f'data/raw/{prefix}-{category}-{index}.png'
                path.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(128,128),(category*20,index*5,200 if field else 10)).save(path)
                rows.append({'sample_id':f'{prefix}-{category}-{index}',
                             'image_path':path.relative_to(tmp_path).as_posix(),
                             'image_sha256':common.digest(path),'category_id':str(category),
                             'object_id':f'{prefix}-object-{category}-{index//4 if field else index}',
                             'group_id':f'{prefix}-group-{category}-{index//4 if field else index}',
                             'session_id':'test-session','source_dataset':'field' if field else 'public',
                             'review_status':'approved'})
        return rows
    train_manifest=tmp_path/'train.csv';common.write_csv(train_manifest,samples('train',2,False))
    data.freeze_split(train_manifest,'train-v1')
    field_rows=samples('field',20,True)
    field_manifest=tmp_path/'field.csv';common.write_csv(field_manifest,field_rows)
    first=data.freeze_field_test(field_manifest,'field-v1','train-v1')
    for name in ('model-a','model-b'):
        bundle=tmp_path/name
        common.write_json(bundle/'metadata.json',{'status':'frozen','sha256':name,
                         'model_version':name,'data_version':'train-v1','acceptance':{}})
        common.write_json(bundle/'release-files.json',{})
    class Runner:
        def __init__(self,bundle):
            self.metadata=common.read_json(bundle/'metadata.json')
            self.labels=list(common.EXPECTED_LABELS)
        def predict_tensor(self,array):
            return np.eye(10,dtype=np.float32)[int(array[0])]
    monkeypatch.setattr(release,'LiteRunner',Runner)
    monkeypatch.setattr(release,'verify',lambda *args:None)
    monkeypatch.setattr(release,'prepare',lambda rows:(
        np.array([[int(r['category_id'])] for r in rows]),np.array([int(r['category_id']) for r in rows])))
    result=release.evaluate(tmp_path/'model-a','test','field-v1','model-a')
    for row in field_rows:
        row['sample_id']='renamed-'+row['sample_id']
        row['object_id']='renamed-'+row['object_id']
        row['group_id']='renamed-'+row['group_id']
    common.write_csv(field_manifest,list(reversed(field_rows)))
    second=data.freeze_field_test(field_manifest,'field-v2','train-v1')
    assert first['files']['test']['sha256']!=second['files']['test']['sha256']
    def forbidden_prepare(*args):
        pytest.fail('Reused independent photos must be rejected before prediction')
    monkeypatch.setattr(release,'prepare',forbidden_prepare)
    with pytest.raises(ValueError,match='photo'):
        release.evaluate(tmp_path/'model-b','test','field-v2','model-b')
    assert result['image_sha256s']==sorted(r['image_sha256'] for r in field_rows)
    assert not (tmp_path/'experiments/reports/evaluations/model-b/field-v2-test.json').exists()


@pytest.mark.parametrize('reused',[False,True])
def test_legacy_test_photo_identities_are_recovered_from_frozen_manifest(tmp_path,monkeypatch,reused):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    manifest=tmp_path/'data/splits/field-old/test.csv'
    common.write_csv(manifest,[{'sample_id':'old','image_sha256':'used-photo'}])
    common.write_json(tmp_path/'experiments/reports/evaluations/model-a/field-old-test.json',{
        'split':'test','data_version':'field-old','manifest_sha256':common.digest(manifest),'model_sha256':'model-a'})
    rows=[{'image_sha256':'used-photo' if reused else 'fresh-photo'}]
    if reused:
        with pytest.raises(ValueError,match='photos were already used'):
            release.check_test_model_binding('field-new','new-manifest','model-b',rows)
    else:
        release.check_test_model_binding('field-new','new-manifest','model-b',rows)


def test_unavailable_legacy_photo_identities_do_not_silently_allow_test_reuse(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    common.write_json(tmp_path/'experiments/reports/evaluations/model-a/field-old-test.json',{
        'split':'test','data_version':'field-old','manifest_sha256':'archived-manifest','model_sha256':'model-a'})
    with pytest.raises(ValueError,match='restore the original frozen test.csv'):
        release.check_test_model_binding('field-new','new-manifest','model-b',[{'image_sha256':'new-photo'}])


def test_partially_reused_test_photos_are_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    common.write_json(tmp_path/'experiments/reports/evaluations/model-a/field-old-test.json',{
        'split':'test','data_version':'field-old','manifest_sha256':'old-manifest','model_sha256':'model-a',
        'image_sha256s':['used-photo','other-used-photo']})
    with pytest.raises(ValueError,match='photos were already used'):
        release.check_test_model_binding('field-new','new-manifest','model-b',[
            {'image_sha256':'new-photo'},{'image_sha256':'used-photo'}])
