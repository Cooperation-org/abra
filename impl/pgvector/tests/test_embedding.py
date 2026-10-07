"""Embed service: same vectors as in-process, and fallback when it can't answer."""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import embed_server  # noqa: E402
import embedding  # noqa: E402


@pytest.fixture
def short_tmp():
    # AF_UNIX paths are capped near 104 bytes on macOS; pytest tmp paths can exceed it.
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="abra-"))
    yield d
    for p in d.iterdir():
        p.unlink()
    d.rmdir()


@pytest.fixture
def service(short_tmp, monkeypatch):
    sock = short_tmp / "e.sock"
    monkeypatch.setenv("ABRA_EMBED_SOCKET", str(sock))
    server = embed_server.Server(str(sock), embed_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield sock
    server.shutdown()
    server.server_close()


def test_service_matches_in_process(service):
    for text in ("budget review for the grant", "ltq1", "x" * 5000):
        via_service = embedding._from_service(text)
        assert via_service is not None
        assert via_service == pytest.approx(embedding.local_model().encode(text).tolist(), abs=1e-5)


@pytest.mark.parametrize("request_line, error", (
    (b'{"model": "some-other-model", "text": "t"}\n', "service model is"),
    (b'{"model": "all-MiniLM-L6-v2"}\n', "needs a text string"),
    (b'not json\n', "must be JSON"),
))
def test_service_rejects_bad_requests(service, request_line, error):
    import json
    import socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(str(service))
        s.sendall(request_line)
        reply = json.loads(s.makefile("rb").readline())
    assert error in reply["error"]


@pytest.mark.parametrize("make_socket", (
    lambda p: None,                 # no socket file
    lambda p: p.write_text(""),     # stale file, nothing listening
))
def test_falls_back_without_service(short_tmp, monkeypatch, make_socket):
    sock = short_tmp / "e.sock"
    make_socket(sock)
    monkeypatch.setenv("ABRA_EMBED_SOCKET", str(sock))
    assert embedding._from_service("text") is None
    assert len(embedding.encode("text")) == 384
