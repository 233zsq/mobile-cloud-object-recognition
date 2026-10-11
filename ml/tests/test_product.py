import io

import pytest
from PIL import Image

from recognition import collect, product
from recognition.common import read_csv


def test_product_download_preserves_provenance_duplicates_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(product, 'ROOT', tmp_path)
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    monkeypatch.setattr(product, 'heldout_test_rows', lambda: [])
    monkeypatch.setattr(product.time, 'sleep', lambda _: None)
    content = io.BytesIO(); Image.new('RGB', (256, 128), 'red').save(content, 'JPEG')
    calls = []
    def fetch(url, *args, **kwargs):
        calls.append(url)
        return content.getvalue()
    monkeypatch.setattr(collect, 'fetch', fetch)
    sources = tmp_path / 'sources.tsv'
    sources.write_text('https://cbu01.alicdn.com/one.jpg\thttps://detail.1688.com/offer/1.html\n'
                       'https://cbu01.alicdn.com/two.jpg\thttps://detail.1688.com/offer/2.html\n')
    report = product.collect_products(sources, tmp_path/'output')
    assert report['downloaded'] == report['candidate_count'] == 1 and len(report['skipped']) == 1
    row = read_csv(tmp_path/'output/candidates.csv')[0]
    assert row['source_dataset'] == 'web_product' and row['license'] == product.RIGHTS
    assert row['review_status'] == 'pending' and row['source_url'].endswith('/1.html')
    assert (tmp_path/row['image_path']).read_bytes() == content.getvalue()
    calls.clear()
    assert product.collect_products(sources, tmp_path/'output')['downloaded'] == 0
    assert calls == ['https://cbu01.alicdn.com/two.jpg']


def test_reserved_identity_is_not_written(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(product, 'ROOT', tmp_path)
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    content = io.BytesIO(); Image.new('RGB', (256, 128)).save(content, 'JPEG')
    monkeypatch.setattr(collect, 'fetch', lambda *a, **kw: content.getvalue())
    monkeypatch.setattr(product, 'heldout_test_rows', lambda: [{'image_sha256': hashlib.sha256(content.getvalue()).hexdigest()}])
    sources = tmp_path/'sources.tsv'
    sources.write_text('https://cbu01.alicdn.com/test.jpg\thttps://detail.1688.com/offer/1.html\n')
    assert product.collect_products(sources, tmp_path/'output')['candidate_count'] == 0
    assert not list((tmp_path/'data/raw/web_product').rglob('*.jpg'))


@pytest.mark.parametrize('image', ['http://cbu01.alicdn.com/test.jpg', 'https://127.0.0.1/a.jpg',
                                  'https://cbu01.alicdn.com/a.jpg,https://cbu01.alicdn.com/b.jpg'])
def test_unobserved_or_combined_image_urls_are_rejected(image):
    with pytest.raises(ValueError):
        product.checked_urls(image, 'https://detail.1688.com/offer/1.html')
