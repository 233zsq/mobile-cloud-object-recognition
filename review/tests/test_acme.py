"""Protect the shared HTTP/443 configuration during renewal failures."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('review_acme', Path(__file__).parents[1] / 'deploy/acme.py')
acme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acme)


def site_fixture(tmp_path, monkeypatch):
    site = tmp_path / 'nginx.conf'
    original = b'limit_req_zone unchanged;\n\n' + acme.HTTP_BLOCK + b'\nserver { listen 443 ssl; KEEP_ALL_BYTES; }\n'
    site.write_bytes(original)
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setattr(acme, 'reload_nginx', lambda: None)
    return site, state, original


def test_challenge_restores_shared_site_after_failure(tmp_path, monkeypatch):
    site, state, original = site_fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match='signing failed'):
        with acme.challenge_route(site, state):
            assert site.read_bytes().endswith(b'server { listen 443 ssl; KEEP_ALL_BYTES; }\n')
            assert b'/.well-known/acme-challenge/' in site.read_bytes()
            raise RuntimeError('signing failed')
    assert site.read_bytes() == original
    assert not (state / 'http-state.json').exists()


def test_concurrent_backend_change_is_not_overwritten(tmp_path, monkeypatch):
    site, state, _ = site_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='concurrently'):
        with acme.challenge_route(site, state):
            site.write_bytes(site.read_bytes() + b'# another deploy\n')
    assert site.read_bytes().endswith(b'# another deploy\n')
    assert (state / 'http-original.conf').exists()


def test_unknown_http_block_refused_before_edit(tmp_path, monkeypatch):
    site, state, _ = site_fixture(tmp_path, monkeypatch)
    site.write_bytes(b'server { listen 80; different; }')
    with pytest.raises(ValueError, match='Port 80 block differs'):
        with acme.challenge_route(site, state):
            pytest.fail('must not start issuance')
    assert site.read_bytes() == b'server { listen 80; different; }'


def test_interrupted_patch_recovered(tmp_path, monkeypatch):
    site, state, original = site_fixture(tmp_path, monkeypatch)
    patched = acme.patched_http(original)
    (state / 'http-original.conf').write_bytes(original)
    (state / 'http-state.json').write_text(json.dumps({
        'original': acme.digest(original), 'patched': acme.digest(patched), 'mode': 0o644,
    }))
    site.write_bytes(patched)
    acme.restore_http(site, state)
    assert site.read_bytes() == original


def test_ip_issuance_uses_http_webroot_and_isolated_staging():
    command = acme.certificate_command('issue-staging')
    assert '--webroot' in command and '--staging' in command
    assert str(Path('/etc/letsencrypt-campus-review-staging')) in command
    assert '--ip-address' in command and '--preferred-profile' in command
    assert '--nginx' not in command and '--standalone' not in command
