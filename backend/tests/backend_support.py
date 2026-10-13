"""Reusable isolated inference fake; never calls the real model worker."""

class ReadyModel:
    version = "campus-gpu-v1"
    def __init__(self):
        self.images = []
    def health(self):
        return {"model_loaded": True}
    def predict(self, image):
        self.images.append(image)
        return {"model_version":self.version,"model_sha256":"a"*64,
                "predicted_id":0,"label_key":"cup","confidence":0.9,"low_confidence":False,
                "scores":[0.9]+[0.1/9]*9,"preprocess_ms":1.0,"inference_ms":2.0,"model_call_ms":3.0}
