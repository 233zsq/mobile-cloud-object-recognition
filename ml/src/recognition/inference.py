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
        self.scope_policy=None
        if m.get('scope_output') is not None:
            name=m.get('scope_policy_file')
            if not isinstance(name,str) or Path(name).name!=name:
                raise ValueError('Expected a local scope-policy filename')
            policy_path=self.release/name
            if digest(policy_path)!=m.get('scope_policy_sha256'):
                raise ValueError('Scope policy SHA-256 mismatch')
            policy=read_json(policy_path)
            identity={'model_version':m['model_version'],'model_sha256':m['sha256'],
                      'labels_sha256':m['labels_sha256'],'category_version':m['category_version'],
                      'preprocessing_version':SPEC['version']}
            if (any(policy.get(k)!=v for k,v in identity.items())
                    or policy.get('rule')!='learned_knownness_v1'
                    or policy.get('policy_version')!='scope-knownness-v1'
                    or policy.get('status') not in ('experimental','frozen')):
                raise ValueError('Scope policy identity/contract mismatch')
            for key in ('confidence_threshold','margin_threshold','knownness_threshold'):
                value=policy.get(key)
                if type(value) not in (int,float) or not np.isfinite(value) or not 0<=value<=1:
                    raise ValueError('Invalid scope policy threshold')
            self.scope_policy={**policy,'policy_sha256':m['scope_policy_sha256']}
        from ai_edge_litert.interpreter import Interpreter
        self.interpreter=Interpreter(model_content=(self.release/"model.tflite").read_bytes(),num_threads=threads)
        self.interpreter.allocate_tensors()
        if len(self.interpreter.get_input_details())!=1:
            raise ValueError('Expected one model input')
        self.input=self.interpreter.get_input_details()[0]
        outputs=self.interpreter.get_output_details()
        score_index=m.get('score_output_index',0)
        if type(score_index) is not int or not 0<=score_index<len(outputs):
            raise ValueError('Invalid class-score output position')
        self.output=outputs[score_index]
        self.scope_output=None
        scope=m.get('scope_output')
        if scope is not None:
            if (not isinstance(scope,dict) or type(scope.get('index')) is not int or not 0<=scope['index']<len(outputs)
                    or scope['index']==score_index or len(outputs)!=2
                    or scope!={'index':scope['index'],'shape':[1,1],'dtype':'float32','interpretation':'knownness'}):
                raise ValueError('Invalid learned scope-output contract')
            self.scope_output=outputs[scope['index']]
            if self.scope_output['shape'].tolist()!=[1,1] or self.scope_output['dtype']!=np.float32:
                raise ValueError('Actual scope tensor differs from contract')
        elif len(outputs)!=1 or score_index!=0:
            raise ValueError('Unexpected extra output without scope contract')
        if self.input["shape"].tolist()!=[1,224,224,3] or self.output["shape"].tolist()!=[1,10] or self.input["dtype"]!=np.float32 or self.output["dtype"]!=np.float32:
            raise ValueError("Actual model tensor differs from contract")

    def predict_tensor(self,array):
        return self.predict_outputs(array)['scores']

    def predict_outputs(self,array):
        array=np.asarray(array)
        if array.dtype!=np.float32 or array.shape not in ((224,224,3),(1,224,224,3)) or not np.isfinite(array).all() or array.min()<0 or array.max()>255:
            raise ValueError("Input must be finite float32 RGB 224x224 in 0..255")
        self.interpreter.set_tensor(self.input["index"],array.reshape(1,224,224,3))
        self.interpreter.invoke()
        scores=self.interpreter.get_tensor(self.output["index"])[0].copy()
        if not np.isfinite(scores).all() or np.any(scores<0) or np.any(scores>1) or not np.isclose(scores.sum(),1,atol=1e-4):
            raise ValueError("Invalid softmax output")
        result={'scores':scores}
        if self.scope_output is not None:
            knownness=float(self.interpreter.get_tensor(self.scope_output['index'])[0,0])
            if not np.isfinite(knownness) or not 0<=knownness<=1:
                raise ValueError('Invalid learned scope output')
            result['knownness']=knownness
        return result

    def predict_image(self,path):
        outputs=self.predict_outputs(preprocess(path))
        scores=outputs['scores']
        top=int(scores.argmax())
        result={"predicted_id":top,"label_key":self.labels[top],"confidence":float(scores[top]),"low_confidence":bool(scores[top]<self.metadata["low_confidence_threshold"]),"scores":scores.tolist(),"model_version":self.metadata["model_version"],"model_sha256":self.metadata["sha256"]}
        if 'knownness' in outputs:
            result['knownness']=outputs['knownness']
        return result
