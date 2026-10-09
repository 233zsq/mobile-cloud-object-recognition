"""Real socket/image checks; run using the separate CPU runtime, without Flask."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from PIL import Image

from server import CpuServer, Handler


class Connection(http.client.HTTPConnection):
    def __init__(self,path):
        super().__init__("localhost",timeout=3)
        self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class Engine:
    model_version="campus-gpu-v1"
    model_sha256="a"*64
    def __init__(self):
        self.enter=threading.Event()
        self.release=threading.Event()
        self.release.set()
        self.calls=0
    def predict_image(self,path):
        self.calls+=1
        self.enter.set()
        self.release.wait(2)
        return {"model_version":self.model_version,"model_sha256":self.model_sha256}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix="cpu-test-")
        self.path=str(Path(self.directory.name)/"model.sock")
        self.server=CpuServer(self.path,Handler)
        self.server.engine=Engine()
        self.server.admission=threading.BoundedSemaphore(1)
        self.server.temporary_directory=Path(self.directory.name)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        stream=io.BytesIO()
        Image.new("RGB",(5,5),(128,128,128)).save(stream,format="PNG")
        self.image=stream.getvalue()
    def tearDown(self):
        self.server.engine.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()
    def call(self,body,version="campus-gpu-v1"):
        connection=Connection(self.path)
        try:
            connection.request("POST","/infer",body=body,headers={"X-Model-Version":version})
            response=connection.getresponse()
            return response.status,json.loads(response.read())
        finally:
            connection.close()
    def test_valid_image_and_cleanup(self):
        self.assertEqual(self.call(self.image)[0],200)
        self.assertEqual(self.server.engine.calls,1)
        self.assertEqual([p.name for p in Path(self.directory.name).iterdir()],["model.sock"])
    def test_corrupt_image_and_version_error_never_reach_model(self):
        self.assertEqual(self.call(b"invalid")[0],400)
        self.assertEqual(self.call(self.image,"old-version")[0],409)
        self.assertEqual(self.server.engine.calls,0)
    def test_pixel_limit_before_decode(self):
        stream=io.BytesIO()
        Image.new("1",(4200,3100)).save(stream,format="PNG")
        status,body=self.call(stream.getvalue())
        self.assertEqual(status,413)
        self.assertEqual(body["error"]["code"],"IMAGE_TOO_LARGE")
        self.assertEqual(self.server.engine.calls,0)
    def test_busy_request_does_not_queue_another_prediction(self):
        self.server.engine.release.clear()
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending=executor.submit(self.call,self.image)
            self.assertTrue(self.server.engine.enter.wait(2))
            status,body=self.call(self.image)
            self.assertEqual((status,body["error"]["code"]),(503,"INFERENCE_BUSY"))
            self.server.engine.release.set()
            self.assertEqual(pending.result()[0],200)
        self.assertEqual(self.server.engine.calls,1)


if __name__=="__main__":
    unittest.main()
