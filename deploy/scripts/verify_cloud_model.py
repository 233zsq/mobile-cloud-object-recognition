"""Export actual CPU-host reference/image evidence and input tensors, without training."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import sys
from uuid import uuid4


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def timing(values):
    ordered = sorted(values)
    return {"min":min(values), "mean":statistics.mean(values), "median":statistics.median(values),
            "p95":ordered[max(0, int(len(ordered)*0.95)-1)], "max":max(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--scope", required=True, help="Actual host context, e.g. ACTUAL TENCENT CLOUD CPU")
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "image_chain_inputs").mkdir()
    sys.path.insert(0, str(package))
    import numpy as np
    from backend_adapter import CpuModelService
    from campus_cpu_runtime.preprocessing import preprocess
    from verify_package import verify_package
    integrity = verify_package(package)
    engine = CpuModelService(package / "release", threads=1)
    examples = json.loads((package / "release/examples/manifest.json").read_text(encoding="utf-8"))
    cpu = "unknown"
    if Path("/proc/cpuinfo").exists():
        cpu = next((line.split(":",1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), "unknown")
    runtime = {name:importlib.metadata.version(name) for name in ("ai-edge-litert", "numpy", "Pillow")}
    runtime.update(python=platform.python_version(), threads=1)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    reports = {}
    for mode in ("reference_tensor", "image_chain"):
        value = json.loads((package / ("results/cloud-"+mode+".template.json")).read_text(encoding="utf-8"))
        value.update(run_id="tencent-cloud-"+stamp+"-"+mode.replace("_","-"),
                     device=cpu+"; "+platform.platform(), runtime=json.dumps(runtime,sort_keys=True), scope=args.scope)
        value["samples"] = []
        reports[mode] = value
    comparisons = []
    for entry in examples:
        sample_id = entry["sample_id"]
        assert sample_id.replace("-", "").isalnum()
        reference_path = package / "release/examples" / entry["tensor"]
        reference_bytes = reference_path.read_bytes()
        reference = np.frombuffer(reference_bytes, dtype="<f4").reshape(224,224,3).copy()
        image_path = package / "release/examples" / entry["image"]
        generated = preprocess(image_path)
        tensor_scores = engine.runner.predict_tensor(reference)
        image_result = engine.predict_image(image_path)
        tensor_difference = float(np.max(np.abs(tensor_scores-entry["scores"])))
        image_difference = float(np.max(np.abs(np.asarray(image_result["scores"])-entry["scores"])))
        pixel_difference = float(np.max(np.abs(generated-reference)))
        passed = (tensor_difference<=0.001 and image_difference<=0.001 and pixel_difference<=0.001
                  and int(tensor_scores.argmax())==entry["predicted_id"] and image_result["predicted_id"]==entry["predicted_id"])
        if not passed:
            raise ValueError("Actual host consistency failed: "+sample_id)
        reports["reference_tensor"]["samples"].append({"sample_id":sample_id, "scores":tensor_scores.tolist(),
                             "tensor_sha256":hashlib.sha256(reference.astype("<f4").tobytes()).hexdigest()})
        relative = "image_chain_inputs/"+sample_id+".bin"
        with (output/relative).open("xb") as stream:
            stream.write(generated.astype("<f4").tobytes())
        reports["image_chain"]["samples"].append({"sample_id":sample_id,"scores":image_result["scores"],"tensor_file":relative})
        comparisons.append({"sample_id":sample_id,"max_tensor_score_difference":tensor_difference,
                            "max_image_score_difference":image_difference,"max_input_difference":pixel_difference,"passed":passed})
    for mode,report in reports.items():
        write_new(output/("cloud-"+mode+".json"),report)
    first_image = package / "release/examples" / examples[0]["image"]
    for _ in range(20):
        engine.predict_image(first_image)
    measured = [engine.predict_image(package / "release/examples" / examples[i%len(examples)]["image"]) for i in range(100)]
    summary={"scope":args.scope,"at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "cpu":cpu,"os":platform.platform(),"runtime":runtime,"package_integrity":integrity,
             "tensorflow_imported":"tensorflow" in sys.modules,"comparisons":comparisons,
             "benchmark":{"warmup":20,"measured":100,"unit":"ms","includes_network":False,
                          **{field:timing([r[field] for r in measured]) for field in ("preprocess_ms","inference_ms","model_call_ms")}},
             "passed":True}
    write_new(output/"actual-host-summary.json",summary)
    print(json.dumps({"passed":True,"scope":args.scope,"out_dir":str(output),"examples":len(comparisons),
                      "max_score_difference":max(max(c["max_tensor_score_difference"],c["max_image_score_difference"]) for c in comparisons),
                      "max_input_difference":max(c["max_input_difference"] for c in comparisons),"benchmark":summary["benchmark"]}))


if __name__ == "__main__":
    main()
