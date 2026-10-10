from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from recognition import common, coco_test, data, release


def mixed_rows():
    rows=[]
    for category in range(10):
        for index in range(20):
            row={'sample_id':f'{category}-{index}', 'category_id':str(category),
                 'image_sha256':f'crop-{category}-{index}', 'review_status':'approved'}
            if category in coco_test.COCO_IDS:
                row.update(source_dataset='coco2017_val',source_id=f'{category}-{index}',
                           parent_image_sha256=f'parent-{category}-{index}',crop_box='[0,0,100,100]')
            else:
                row.update(source_dataset='field',object_id=f'object-{category}-{index//4}',session_id='field-session')
            rows.append(row)
    return rows


@pytest.mark.parametrize('fault', ['missing_class', 'duplicate_source', 'wrong_source', 'unreviewed', 'missing_object'])
def test_mixed_test_rejects_invalid_or_incomplete_samples(fault):
    rows=mixed_rows()
    coco_test.validate_mixed_rows(rows)
    if fault=='missing_class':rows.pop()
    elif fault=='duplicate_source':rows[1]['source_id']=rows[0]['source_id']
    elif fault=='wrong_source':rows[0]['source_dataset']='open_images'
    elif fault=='unreviewed':rows[0]['review_status']='pending'
    else:next(row for row in rows if row['category_id']=='3')['object_id']=''
    with pytest.raises(ValueError):coco_test.validate_mixed_rows(rows)


def test_reserved_original_and_crop_are_blocked_from_training(tmp_path, monkeypatch):
    monkeypatch.setattr(data,'ROOT',tmp_path)
    reservation=tmp_path/'data/test-reservations/coco-v1'
    common.write_csv(reservation/'samples.csv',[{'sample_id':'coco-test','image_sha256':'crop',
                    'parent_image_sha256':'original','phash':'1234567890abcdef'}],common.FIELDS+coco_test.EXTRA_FIELDS)
    common.write_json(reservation/'reservation.json',{'training_prohibited':True,
                      'manifest_sha256':common.digest(reservation/'samples.csv')})
    for value in ('crop','original'):
        with pytest.raises(ValueError,match='leakage'):
            data.check_isolation([{'image_sha256':value}],data.heldout_test_rows())
    with pytest.raises(ValueError,match='near duplicate'):
        data.check_isolation([{'image_sha256':'reencoded','phash':'1234567890abcdee'}],data.heldout_test_rows())
    common.write_csv(reservation/'samples.csv',[{'sample_id':'tampered'}])
    with pytest.raises(ValueError,match='changed'):data.heldout_test_rows()


def test_recropped_test_source_cannot_be_reused_by_another_model(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    common.write_json(tmp_path/'experiments/reports/evaluations/model-a/mixed-v1-test.json',{
        'split':'test','model_sha256':'model-a','data_version':'mixed-v1','manifest_sha256':'manifest',
        'image_sha256s':['first-crop'],'parent_image_sha256s':['original']})
    with pytest.raises(ValueError,match='photos were already used'):
        release.check_test_model_binding('renamed-test','new-manifest','model-b',[
            {'image_sha256':'different-crop','parent_image_sha256':'original'}])


def test_mixed_evaluation_does_not_update_field_acceptance_or_release(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    rows=mixed_rows()
    metadata={'status':'frozen','model_version':'candidate','sha256':'model','data_version':'training',
              'category_version':'campus-10-v4','acceptance':{'independent_field_accuracy':'pending'}}
    bundle=tmp_path/'release';common.write_json(bundle/'metadata.json',metadata)
    original=common.digest(bundle/'metadata.json')
    class Runner:
        def __init__(self,path):self.metadata=metadata;self.labels=list(common.EXPECTED_LABELS)
        def predict_tensor(self,array):return np.eye(10,dtype=np.float32)[int(array[0])]
    monkeypatch.setattr(release,'LiteRunner',Runner)
    monkeypatch.setattr(release,'load_split',lambda version,split,**kwargs:(rows,{
        'purpose':coco_test.PURPOSE,'category_version':'campus-10-v4','files':{'test':{'sha256':'manifest'}}}) if split=='test' else ([],{}))
    monkeypatch.setattr(release,'verify',lambda *args,**kwargs:None)
    monkeypatch.setattr(release,'prepare',lambda rows:(np.array([[int(r['category_id'])] for r in rows]),np.array([int(r['category_id']) for r in rows])))
    monkeypatch.setattr(release,'metrics',lambda y,scores:{'accuracy':1.,'macro_f1':1.})
    monkeypatch.setattr(release,'render_evaluation',lambda out,*args:out.with_suffix('.png').write_bytes(b'confusion-matrix'))
    monkeypatch.setattr(release,'annex_evaluation',lambda *args:pytest.fail('Mixed test must not annex field acceptance'))
    result=release.evaluate(bundle,'test','mixed-v1','model')
    assert result['independent_phone_acceptance'] is False
    assert result['results_by_source']=={'coco2017_val':{'count':120,'accuracy':1.},'field':{'count':80,'accuracy':1.}}
    assert 'accuracy_passed' not in result['acceptance']
    assert common.digest(bundle/'metadata.json')==original
    assert release.evaluate(bundle,'test','mixed-v1','model')==result


def test_coco_download_refuses_full_archive_response(monkeypatch):
    class Response:
        status=200
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):pytest.fail('Do not read a full archive when Range was ignored')
    monkeypatch.setattr(coco_test.urllib.request,'urlopen',lambda *args,**kwargs:Response())
    with pytest.raises(ValueError,match='bounded byte range'):
        coco_test.download(coco_test.ANNOTATION_URL,1024,'0-1023')


def test_visual_review_can_reject_but_cannot_change_test_selection(tmp_path,monkeypatch):
    monkeypatch.setattr(coco_test,'ROOT',tmp_path)
    directory=tmp_path/'data/test-reservations/reserved-v1'
    row={'sample_id':'coco-one','category_id':'0','image_sha256':'crop','review_status':'pending'}
    common.write_csv(directory/'samples.csv',[row],common.FIELDS+coco_test.EXTRA_FIELDS)
    common.write_json(directory/'reservation.json',{'manifest_sha256':common.digest(directory/'samples.csv')})
    reviewed=tmp_path/'review.csv'
    common.write_csv(reviewed,[{**row,'review_status':'rejected','review_reason':'jar, not a drinking cup'}],common.FIELDS+coco_test.EXTRA_FIELDS)
    assert coco_test.reviewed_selection('reserved-v1',reviewed)[0][0]['review_status']=='rejected'
    common.write_csv(reviewed,[{**row,'image_sha256':'another-photo','review_status':'approved'}],common.FIELDS+coco_test.EXTRA_FIELDS)
    with pytest.raises(ValueError,match='Only visual approval'):
        coco_test.reviewed_selection('reserved-v1',reviewed)


def test_mixed_freeze_requires_complete_field_batch_and_hashes_real_pixels(tmp_path,monkeypatch):
    category=common.categories('campus-10-v4')
    for module in (common,data,coco_test):monkeypatch.setattr(module,'ROOT',tmp_path)
    category_file=tmp_path/'shared/category-versions/campus-10-v4.json'
    common.write_json(category_file,category)
    dev={'category_version':'campus-10-v4','categories_sha256':common.digest(category_file)}
    monkeypatch.setattr(data,'load_split',lambda *args,**kwargs:([],dev))
    rows=mixed_rows();rng=np.random.default_rng(72)
    for row in rows:
        path=tmp_path/'data/raw'/f"{row['sample_id']}.png";path.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(rng.integers(0,256,(128,128,3),dtype=np.uint8)).save(path)
        row.update(image_path=path.relative_to(tmp_path).as_posix(),image_sha256=common.digest(path))
    public=[r for r in rows if int(r['category_id']) in coco_test.COCO_IDS]
    field=[r for r in rows if int(r['category_id']) in coco_test.FIELD_IDS]
    directory=tmp_path/'data/test-reservations/reserved'
    common.write_csv(directory/'samples.csv',public,common.FIELDS+coco_test.EXTRA_FIELDS)
    common.write_json(directory/'reservation.json',{'manifest_sha256':common.digest(directory/'samples.csv'),
        **dev,'protocol':{'per_class':20}})
    reviewed=tmp_path/'review.csv';common.write_csv(reviewed,public,common.FIELDS+coco_test.EXTRA_FIELDS)
    field_file=tmp_path/'field.csv';common.write_csv(field_file,field[:-1])
    with pytest.raises(ValueError,match='twenty'):
        coco_test.freeze('mixed-v1','reserved',reviewed,field_file,'dev')
    assert not (tmp_path/'data/splits/mixed-v1').exists()
    common.write_csv(field_file,field)
    frozen=coco_test.freeze('mixed-v1','reserved',reviewed,field_file,'dev')
    assert frozen['files']['test']['count']==200 and frozen['independent_phone_acceptance'] is False
    actual=common.read_csv(tmp_path/'data/splits/mixed-v1/test.csv')
    assert all(r['phash'] and r['split_name']=='test' and r['data_version']=='mixed-v1' for r in actual)
