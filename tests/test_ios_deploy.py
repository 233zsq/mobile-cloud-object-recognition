"""Regression checks for TLS scope and the public static-file boundary."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import subprocess
import ssl

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'deploy/scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


tls = module('public_tls')
publisher = module('publish_ios')
verifier = module('verify_server')


def test_server_verifier_keeps_system_ca_and_hostname_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, 'BASE', tmp_path)
    context = verifier.tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.cert_store_stats()['x509_ca'] > 0


def test_legacy_certificate_is_added_without_replacing_system_trust(tmp_path, monkeypatch):
    certificate = tmp_path / 'shared/server.crt'
    certificate.parent.mkdir()
    certificate.write_text('test certificate path only')
    calls = []
    class Context:
        def load_verify_locations(self, **kwargs):
            calls.append(kwargs)
    context = Context()
    monkeypatch.setattr(verifier, 'BASE', tmp_path)
    monkeypatch.setattr(verifier.ssl, 'create_default_context', lambda: context)
    assert verifier.tls_context() is context
    assert calls == [{'cafile': str(certificate)}]


def test_tls_switch_preserves_ports_routes_and_unrelated_bytes():
    before = ('server { listen 80; return 308 https://49.232.195.47$request_uri; }\n'
              'server {\n listen 443 ssl;\n'
              ' ssl_certificate /etc/mobile-cloud-backend/tls/server.crt;\n'
              ' ssl_certificate_key /etc/mobile-cloud-backend/tls/server.key;\n'
              ' location /api/ { KEEP_AUTH; }\n location /ios/ { KEEP_STATIC; }\n}\n')
    after = tls.trusted_config(before)
    expected = before.replace('/etc/mobile-cloud-backend/tls/server.crt', str(tls.LINEAGE / 'fullchain.pem'))
    expected = expected.replace('/etc/mobile-cloud-backend/tls/server.key', str(tls.LINEAGE / 'privkey.pem'))
    assert after == expected
    assert tls.trusted_config(after) == after


@pytest.mark.parametrize('text', [
    'ssl_certificate /another/site.crt;\nssl_certificate_key /another/site.key;',
    'ssl_certificate /etc/mobile-cloud-backend/tls/server.crt;\n' * 2,
    'server { listen 443 ssl; }',
])
def test_unrecognized_tls_configuration_is_refused(text):
    with pytest.raises(ValueError, match='Unexpected'):
        tls.trusted_config(text)


def test_readiness_waits_for_old_nginx_workers_without_disabling_tls(monkeypatch):
    calls = []
    def request(*args):
        calls.append(args)
        assert '-k' not in args and '--insecure' not in args
        if len(calls) < 3:
            raise subprocess.CalledProcessError(60, args, stderr='old self-signed worker')
    monkeypatch.setattr(tls, 'run', request)
    monkeypatch.setattr(tls.time, 'sleep', lambda _: None)
    tls.readiness()
    assert len(calls) == 3


def archive(tmp_path, names):
    target = tmp_path / 'web.tar.gz'
    with tarfile.open(target, 'w:gz') as output:
        for name in names:
            item = tarfile.TarInfo(name)
            item.size = 2
            output.addfile(item, io.BytesIO(b'{}'))
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def test_only_the_seven_public_runtime_files_are_published(tmp_path):
    target, digest = archive(tmp_path, publisher.FILES)
    assert set(publisher.bundle_files(target, digest)) == publisher.FILES


@pytest.mark.parametrize('extra', ['../backend.env', 'api tokens.txt', 'tests/core.test.cjs', 'index.html'])
def test_private_extra_traversal_and_duplicate_bundle_members_are_refused(tmp_path, extra):
    target, digest = archive(tmp_path, [*publisher.FILES, extra])
    with pytest.raises(ValueError, match='members'):
        publisher.bundle_files(target, digest)


def test_bundle_digest_must_match_before_extraction(tmp_path):
    target, _ = archive(tmp_path, publisher.FILES)
    with pytest.raises(ValueError, match='hash'):
        publisher.bundle_files(target, '0' * 64)
