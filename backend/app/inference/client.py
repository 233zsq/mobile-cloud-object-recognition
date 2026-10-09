"""Bounded HTTP calls to the independent CPU runtime over a private Unix socket."""

import http.client
import json
import math
import socket

from ..errors import ApiError

MESSAGES = {
    "MODEL_UNAVAILABLE": "推理服务暂不可用，请稍后重试。",
    "MODEL_VERSION_MISMATCH": "请求的模型版本与云端加载版本不一致。",
    "INFERENCE_BUSY": "推理服务忙碌，请稍后重试。",
    "INFERENCE_TIMEOUT": "推理请求超时，请稍后重试。",
    "INVALID_IMAGE": "无法解码有效的单张图片。",
    "UNSUPPORTED_IMAGE": "仅支持非动画 JPEG、PNG 或 WebP 图片。",
    "IMAGE_TOO_LARGE": "图片超过文件大小或解码像素限制。",
}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class ModelClient:
    def __init__(self, path, version, sha256, timeout=15):
        self.path, self.version, self.sha256, self.timeout = path, version, sha256, timeout

    def _request(self, method, path, body=None, timeout=None):
        connection = UnixConnection(self.path, self.timeout if timeout is None else timeout)
        try:
            connection.request(method, path, body=body, headers={"X-Model-Version": self.version})
            response = connection.getresponse()
            raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("Oversized runtime response")
            data = json.loads(raw)
            if response.status != 200:
                code = data.get("error", {}).get("code")
                if code not in MESSAGES or response.status not in (400, 409, 413, 415, 503):
                    raise ValueError("Invalid runtime error")
                raise ApiError(code, MESSAGES[code], response.status)
            if (data.get("model_version"), data.get("model_sha256")) != (self.version, self.sha256):
                raise ValueError("Runtime identity mismatch")
            return data
        except ApiError:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise ApiError("INFERENCE_TIMEOUT", MESSAGES["INFERENCE_TIMEOUT"], 503) from exc
        except (OSError, http.client.HTTPException, ValueError, TypeError, AttributeError) as exc:
            raise ApiError("MODEL_UNAVAILABLE", MESSAGES["MODEL_UNAVAILABLE"], 503) from exc
        finally:
            connection.close()

    def health(self):
        value = self._request("GET", "/health", timeout=1)
        if value.get("model_loaded") is not True:
            raise ApiError("MODEL_UNAVAILABLE", MESSAGES["MODEL_UNAVAILABLE"], 503)
        return value

    def predict(self, image):
        result = self._request("POST", "/infer", image)
        try:
            scores = result["scores"]
            predicted = result["predicted_id"]
            assert type(predicted) is int and 0 <= predicted <= 9
            assert isinstance(scores, list) and len(scores) == 10
            assert all(type(s) in (int, float) and math.isfinite(s) and 0 <= s <= 1 for s in scores)
            assert abs(sum(scores) - 1) <= 0.0001
            assert predicted == max(range(10), key=scores.__getitem__)
            assert type(result["confidence"]) in (int, float) and result["confidence"] == scores[predicted]
            assert type(result["low_confidence"]) is bool
            assert isinstance(result["label_key"], str)
            for field in ("preprocess_ms", "inference_ms", "model_call_ms"):
                assert type(result[field]) in (int, float) and math.isfinite(result[field]) and result[field] >= 0
            assert result["model_call_ms"] >= result["preprocess_ms"] + result["inference_ms"] - 0.001
        except (KeyError, AssertionError, TypeError) as exc:
            raise ApiError("MODEL_UNAVAILABLE", MESSAGES["MODEL_UNAVAILABLE"], 503) from exc
        return result


def init_inference(app):
    path = app.config["INFERENCE_SOCKET"]
    app.extensions["inference_client"] = ModelClient(
        path, app.config["INFERENCE_MODEL_VERSION"], app.config["INFERENCE_MODEL_SHA256"],
        app.config["INFERENCE_TIMEOUT_SECONDS"],
    ) if path else None
