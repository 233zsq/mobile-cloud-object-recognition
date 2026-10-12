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


def test_legacy_package_uses_existing_category_registration_without_fabricating_seed(tmp_path, monkeypatch):
    v1, v2 = tmp_path / 'v1', tmp_path / 'v2'
    v1.mkdir()
    v2.mkdir()
    (v2 / 'categories.json').write_text('{}')
    commands = []
    monkeypatch.setattr(module, 'run', lambda args, cwd: commands.append(args))
    module.register_packages(Path('/python'), tmp_path, [{'package': str(v2)}, {'package': str(v1)}])
    assert len(commands) == 3
    assert 'db-seed' in commands[0] and commands[0][-1] == str(v2 / 'categories.json')
    assert all('register-model' in command for command in commands[1:])
