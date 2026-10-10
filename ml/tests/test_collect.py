from pathlib import Path
import pytest
from recognition import collect


def test_small_commons_original_gets_a_supported_scaled_thumbnail(monkeypatch):
    calls=[]
    def api(params):
        calls.append(params)
        if params.get('list')=='categorymembers':
            return {'query':{'categorymembers':[{'pageid':5,'title':'File:cup.jpg'}] if params['cmtitle']=='Category:Mugs' else []}}
        if params.get('list')=='search':return {'query':{'search':[]}}
        width=params['iiurlwidth']
        return {'query':{'pages':{'5':{'pageid':5,'title':'File:cup.jpg','imageinfo':[{'width':550,'height':400,'mime':'image/jpeg','url':'original','thumburl':'original' if width==960 else 'scaled-500','thumbwidth':550 if width==960 else 500,'thumbheight':400 if width==960 else 364}]}}}}
    monkeypatch.setattr(collect,'api',api)
    _,_,info=next(collect.candidates('cup'))
    assert info['thumburl']=='scaled-500' and info['requested_thumbnail_width']==500
    assert [c['iiurlwidth'] for c in calls if 'iiurlwidth' in c]==[960,500]


def test_download_quota_counts_both_providers(tmp_path,monkeypatch):
    monkeypatch.setattr(collect,"ROOT",tmp_path)
    for provider,n in (("commons",120),("openimages",120)):
        directory=tmp_path/"data/raw"/provider/"pencil_case"
        directory.mkdir(parents=True)
        for i in range(n):
            (directory/f"{i}.jpg").write_bytes(b"x")
    with pytest.raises(ValueError,match="quota reached"):
        collect.store_download(tmp_path/"data/raw/commons/pencil_case/new.jpg",b"x","pencil_case")
    collect.store_download(tmp_path/"data/raw/commons/pencil_case/0.jpg",b"updated","pencil_case")


def test_bad_openimages_category_refused_before_network():
    with pytest.raises(ValueError,match="eight boxable"):
        collect.collect_openimages(["charger"])


def test_expanded_cap_is_explicit_and_still_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    directory = tmp_path / 'data/raw/commons/key'
    directory.mkdir(parents=True)
    for n in range(240):
        (directory / f'{n}.jpg').write_bytes(b'x')
    collect.store_download(directory / 'new.jpg', b'x', 'key', class_cap=750)
    with pytest.raises(ValueError, match='1..750'):
        collect.store_download(directory / 'overflow.jpg', b'x', 'key', class_cap=751)
    with pytest.raises(ValueError, match='max-new'):
        collect.collect_commons(['key'], 750, class_cap=750, max_new=2001)


def test_old_commons_ids_are_skipped_before_metadata_and_download(monkeypatch):
    calls=[]
    def api(params):
        calls.append(params)
        if params.get('list') == 'categorymembers':
            return {'query': {'categorymembers': [{'pageid': 1, 'title': 'old'}, {'pageid': 2, 'title': 'new'}]}}
        return {'query': {'search': []}}
    monkeypatch.setattr(collect, 'api', api)
    assert list(collect.candidate_ids('key', 1, {'1'})) == [2]
    assert len(calls) == 1


def test_commons_resume_reuses_public_api_page_but_never_caches_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    monkeypatch.setattr(collect.time, 'sleep', lambda _: None)
    calls=[]
    def fetch(*args):
        calls.append(args)
        return b'{"query":{"categorymembers":[]}}'
    monkeypatch.setattr(collect, 'fetch', fetch)
    assert collect.api({'action':'query'}) == collect.api({'action':'query'})
    assert len(calls) == 1
    monkeypatch.setattr(collect, 'fetch', lambda *args: b'{"error":{"code":"maxlag"}}')
    for _ in range(2):
        with pytest.raises(ValueError, match='maxlag'):
            collect.api({'action':'different'})
    assert len(list((tmp_path/'data/raw/commons-api-cache').rglob('*.json'))) == 1


def test_expansion_adds_small_crop_candidates_but_keeps_depictions_out(tmp_path, monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    monkeypatch.setattr(collect, 'categories', lambda:{'categories':[{'id':2,'label_key':'book'}]})
    labels=b'ImageID,LabelName,Confidence\na,/m/0bt_c3,1\nb,/m/0bt_c3,1\nc,/m/0bt_c3,1\n'
    metadata=b'ImageID,OriginalLandingURL,OriginalURL,Author,License\na,https://example.org/a,https://example.org/a.jpg,A,CC-BY\nb,https://example.org/b,https://example.org/b.jpg,A,CC-BY\nc,https://example.org/c,https://example.org/c.jpg,A,CC-BY\n'
    boxes=b'ImageID,LabelName,XMin,XMax,YMin,YMax,IsGroupOf,IsDepiction,IsTruncated\na,/m/0bt_c3,0,.4,0,.3,0,0,0\nb,/m/0bt_c3,0,.6,0,.6,0,0,0\nc,/m/0bt_c3,0,.6,0,.6,0,1,0\n'
    class Response(io.BytesIO):
        def __init__(self, data):
            super().__init__(data); self.headers={'Content-Length':str(len(data))}
    monkeypatch.setattr(collect.urllib.request, 'urlopen', lambda request, **kwargs: Response(
        boxes if 'bbox' in request.full_url else labels if 'imagelabels' in request.full_url else metadata))
    def fetch(url, *args):
        stream=io.BytesIO(); Image.new('RGB',(200,200),'red' if '/a.' in url else 'blue').save(stream,'JPEG')
        return stream.getvalue()
    monkeypatch.setattr(collect, 'fetch', fetch)
    assert [r['source_id'] for r in collect.collect_openimages(['book'],80,'public-test')] == ['b']
    rows=collect.collect_openimages(['book'],750,'public-test',class_cap=750,max_new=1,include_crop_candidates=True)
    assert {r['source_id'] for r in rows} == {'a','b'}
    assert all(r['review_status']=='pending' for r in rows)


def test_response_limit_is_checked_before_read(monkeypatch):
    class Response:
        headers={"Content-Length":"1000"}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):raise AssertionError("Oversize body should never be read")
    monkeypatch.setattr(collect.urllib.request,"urlopen",lambda *a,**k:Response())
    with pytest.raises(ValueError,match="byte limit"):
        collect.fetch("https://example.org/image",100)


def test_openimages_index_cumulative_budget_blocks_repeated_large_scan(tmp_path,monkeypatch):
    from recognition.common import write_json
    monkeypatch.setattr(collect,"ROOT",tmp_path)
    write_json(tmp_path/"data/raw/openimages-index/scan.json",{"bytes":1015172531})
    monkeypatch.setattr(collect.urllib.request,"urlopen",lambda *a,**k:pytest.fail("Do not repeat the full train index scan"))
    with pytest.raises(ValueError,match="already scanned"):
        collect.collect_openimages(["book"],80,"train")


def test_small_openimages_indexes_are_cached_and_conflicting_targets_skipped(tmp_path,monkeypatch):
    import io
    from PIL import Image
    monkeypatch.setattr(collect,"ROOT",tmp_path)
    monkeypatch.setattr(collect,"categories",lambda:{"categories":[{"id":2,"label_key":"book"},{"id":0,"label_key":"cup"}]})
    labels=b'ImageID,LabelName,Confidence\na,/m/0bt_c3,1\nb,/m/0bt_c3,1\nb,/m/02jvh9,1\n'
    metadata=b'ImageID,OriginalLandingURL,OriginalURL,Author,License\na,https://example.org/a,https://example.org/a.jpg,Author,CC-BY\nb,https://example.org/b,https://example.org/b.jpg,Author,CC-BY\n'
    requests=[]
    class Response(io.BytesIO):
        def __init__(self,blob):
            super().__init__(blob);self.headers={"Content-Length":str(len(blob))}
    def urlopen(request,**kwargs):
        requests.append(request.full_url)
        return Response(labels if 'imagelabels' in request.full_url else metadata)
    monkeypatch.setattr(collect.urllib.request,"urlopen",urlopen)
    image=io.BytesIO();Image.new('RGB',(128,128)).save(image,format='JPEG')
    monkeypatch.setattr(collect,"fetch",lambda *a,**k:image.getvalue())
    first=collect.collect_openimages(["book","cup"],80)
    assert [r['source_id'] for r in first]==['a']
    second=collect.collect_openimages(["book","cup"],80)
    assert len(second)==1 and len(requests)==2
    assert collect.read_json(tmp_path/"data/raw/openimages-index/budget.json")['bytes']==len(labels)+len(metadata)
