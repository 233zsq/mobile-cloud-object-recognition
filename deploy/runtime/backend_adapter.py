"""Thread-safe two-output CPU adapter, packaged with campus_scope_runtime."""
from pathlib import Path
import threading
import time
from campus_scope_runtime.inference import LiteRunner
from campus_scope_runtime.preprocessing import preprocess


class CpuModelService:
    def __init__(self, release=Path(__file__).resolve().parent / 'release', threads=1):
        self.runner = LiteRunner(release, threads=threads)
        self._inference_lock = threading.Lock()

    @property
    def model_version(self):
        return self.runner.metadata['model_version']

    @property
    def model_sha256(self):
        return self.runner.metadata['sha256']

    def predict_image(self, image_path):
        started = time.perf_counter()
        tensor = preprocess(image_path)
        ready = time.perf_counter()
        with self._inference_lock:
            inference_started = time.perf_counter()
            outputs = self.runner.predict_outputs(tensor)
            finished = time.perf_counter()
        scores = outputs['scores']
        top = int(scores.argmax())
        result = {'model_version': self.model_version, 'model_sha256': self.model_sha256,
                  'predicted_id': top, 'label_key': self.runner.labels[top], 'confidence': float(scores[top]),
                  'low_confidence': bool(scores[top] < self.runner.metadata['low_confidence_threshold']),
                  'scores': scores.tolist(), 'preprocess_ms': (ready-started)*1000,
                  'inference_ms': (finished-inference_started)*1000, 'model_call_ms': (finished-started)*1000}
        if 'knownness' in outputs:
            result['knownness'] = outputs['knownness']
        return result
