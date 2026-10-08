"""CPU-only model package reader shared with deployment smoke checks."""
from pathlib import Path
import numpy as np
from .common import EXPECTED_LABELS, digest, read_json
from .preprocessing import SPEC, preprocess


class LiteRunner:
    def __init__(self,release,threads=1,*,_allow_pending=False):
        if not 1<=threads<=8:
            raise ValueError("threads must be 1..8")
        self.release=Path(release)
        self.metadata=read_json(self.release/"metadata.json")
        m=self.metadata
        allowed={'experimental','frozen'} | ({'validation_pending'} if _allow_pending else set())
        if m.get('status') not in allowed:
            raise ValueError('Model release is not verified for inference')
        if digest(self.release/"model.tflite")!=m["sha256"] or digest(self.release/"labels.txt")!=m["labels_sha256"]:
            raise ValueError("Model/labels SHA-256 mismatch")
        self.labels=(self.release/"labels.txt").read_text(encoding="utf-8").splitlines()
        if tuple(self.labels)!=EXPECTED_LABELS or self.labels!=[c["label_key"] for c in m["categories"]] or [c["id"] for c in m["categories"]]!=list(range(10)):
            raise ValueError("Label order/category ID mismatch")
        if m["input"]!=SPEC or m["output"]!={"shape":[1,10],"dtype":"float32","interpretation":"softmax"}:
            raise ValueError("Unsupported preprocessing/tensor contract")
        from ai_edge_litert.interpreter import Interpreter
        self.interpreter=Interpreter(model_content=(self.release/"model.tflite").read_bytes(),num_threads=threads)
        self.interpreter.allocate_tensors()
        self.input=self.interpreter.get_input_details()[0]
        self.output=self.interpreter.get_output_details()[0]
        if self.input["shape"].tolist()!=[1,224,224,3] or self.output["shape"].tolist()!=[1,10] or self.input["dtype"]!=np.float32 or self.output["dtype"]!=np.float32:
            raise ValueError("Actual model tensor differs from contract")

    def predict_tensor(self,array):
        array=np.asarray(array)
        if array.dtype!=np.float32 or array.shape not in ((224,224,3),(1,224,224,3)) or not np.isfinite(array).all() or array.min()<0 or array.max()>255:
            raise ValueError("Input must be finite float32 RGB 224x224 in 0..255")
        self.interpreter.set_tensor(self.input["index"],array.reshape(1,224,224,3))
        self.interpreter.invoke()
        scores=self.interpreter.get_tensor(self.output["index"])[0].copy()
        if not np.isfinite(scores).all() or np.any(scores<0) or np.any(scores>1) or not np.isclose(scores.sum(),1,atol=1e-4):
            raise ValueError("Invalid softmax output")
        return scores

    def predict_image(self,path):
        scores=self.predict_tensor(preprocess(path))
        top=int(scores.argmax())
        return {"predicted_id":top,"label_key":self.labels[top],"confidence":float(scores[top]),"low_confidence":bool(scores[top]<self.metadata["low_confidence_threshold"]),"scores":scores.tolist(),"model_version":self.metadata["model_version"],"model_sha256":self.metadata["sha256"]}
