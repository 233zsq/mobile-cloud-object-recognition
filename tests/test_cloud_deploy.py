import importlib.util
import io
import hashlib
from pathlib import Path
import tarfile

import pytest

spec = importlib.util.spec_from_file_location('cloud_deploy', Path(__file__).parents[1] / 'deploy/scripts/deploy_cloud_models.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('name', ['../escape', '/etc/config', 'backend/.env', 'models/private', 'web/../backend/config'])
def test_source_bundle_rejects_unsafe_or_private_members(tmp_path, name):
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        member = tarfile.TarInfo(name)
        member.size = 1
        output.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(ValueError):
        module.source_files(archive, hashlib.sha256(archive.read_bytes()).hexdigest())


def test_source_bundle_checks_hash_duplicate_names_and_regular_files(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        member = tarfile.TarInfo('SOURCE_REVISION')
        member.size = 3
        output.addfile(member, io.BytesIO(b'abc'))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert module.source_files(archive, digest) == {'SOURCE_REVISION': b'abc'}
    with pytest.raises(ValueError):
        module.source_files(archive, '0' * 64)
    for kind in ('duplicate', 'symlink'):
        with tarfile.open(archive, 'w:gz') as output:
            output.addfile(member, io.BytesIO(b'abc'))
            if kind == 'symlink':
                link = tarfile.TarInfo('backend/link')
                link.type = tarfile.SYMTYPE
                link.linkname = '/etc/config'
                output.addfile(link)
            else:
                output.addfile(member, io.BytesIO(b'abc'))
        with pytest.raises(ValueError):
            module.source_files(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
