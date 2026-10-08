import numpy as np
import pytest
from recognition import common,release,data
from recognition.preprocessing import SPEC


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
        'split':'test','data_version':'field-v1','manifest_sha256':'manifest','model_sha256':'model-one'})
    with pytest.raises(ValueError,match='different model'):
        release.check_test_model_binding(version,manifest_sha256,'model-two')
    release.check_test_model_binding('field-v1','manifest','model-one')
    release.check_test_model_binding('field-v2','new-manifest','model-two')
