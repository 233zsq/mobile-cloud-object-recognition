"""Execute the actual SSH payload locally with an offline HTTP response."""
import shlex
import subprocess
import sys

import pytest

from recognition.collect_increment import remote_fetch_command


@pytest.mark.parametrize(
    "url,limit,declared,error",
    [
        ("https://commons.wikimedia.org/w/api.php?search=cup%27s+image&format=json", 10, 5, None),
        ("https://upload.wikimedia.org/example.jpg", 4, 5, "Response exceeds byte limit"),
        ("https://upload.wikimedia.org/example.jpg", 4, 0, "Response exceeds byte limit"),
        ("https://example.com/image.jpg", 10, 5, "Unsupported collection origin"),
    ],
)
def test_remote_payload_is_executable_and_preserves_origin_and_size_limits(url, limit, declared, error):
    command = shlex.split(remote_fetch_command(url, limit))
    assert command[:2] == ["python3", "-c"]
    assert command[3:] == [url, str(limit)]
    code = f"""
import io, sys, urllib.request
class Response(io.BytesIO):
    headers = {{'Content-Length': {str(declared)!r}}}
def offline_response(request, timeout):
    assert request.full_url == {url!r}
    assert timeout == 30
    return Response(b'photo')
urllib.request.urlopen = offline_response
sys.argv = ['remote-fetch', {url!r}, {str(limit)!r}]
exec(compile({command[2]!r}, '<remote-fetch>', 'exec'))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        timeout=20,
    )
    if error is None:
        assert result.returncode == 0, result.stderr.decode()
        assert result.stdout == b"photo"
    else:
        assert result.returncode != 0
        assert error in result.stderr.decode()
        assert result.stdout == b""
