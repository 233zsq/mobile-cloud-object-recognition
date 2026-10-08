"""Explicit synthetic integration fixtures, excluded from formal experiments."""
from pathlib import Path
import numpy as np
from PIL import Image
from .common import ROOT,FIELDS,categories,digest,now,read_json,safe_name,write_csv,write_json


def smoke(identifier,epochs=1):
    from .training import train
    from .release import export,verify,benchmark
    safe_name(identifier)
    version=identifier+"-data"
    directory=ROOT/"data/splits"/version
    if directory.exists():
        raise ValueError("Smoke ID exists; use a new ID")
    rng=np.random.default_rng(42)
    rows={"train":[],"validation":[]}
    for category in range(10):
        for index in range(4):
            sid=f"{identifier}-c{category}-{index}"
            path=ROOT/"data/raw/smoke"/identifier/(sid+".png")
            path.parent.mkdir(parents=True,exist_ok=True)
            array=rng.integers(0,256,(160+category*5,260,3),dtype=np.uint8)
            Image.fromarray(array).save(path)
            name="train" if index<2 else "validation"
            row={k:"" for k in FIELDS}
            row.update(sample_id=sid,image_path=path.relative_to(ROOT).as_posix(),image_sha256=digest(path),category_id=str(category),group_id=sid,review_status="approved",review_reason="synthetic integration fixture; not object labels",split_name=name,data_version=version,source_dataset="synthetic_smoke")
            rows[name].append(row)
    cat=categories()
    metadata={"status":"frozen","purpose":"smoke","data_version":version,"category_version":cat["category_version"],"categories_sha256":digest(ROOT/"shared/categories.json"),"created_at":now(),"seed":42,"files":{},"final_test_status":"not_applicable"}
    for name,items in rows.items():
        path=directory/f"{name}.csv"
        write_csv(path,items)
        metadata["files"][name]={"sha256":digest(path),"count":len(items)}
    write_json(directory/"dataset.json",metadata)
    config=read_json(ROOT/"ml/configs/baseline.json")
    config.update(data_version=version,smoke=True,augmentation=False,max_epochs=epochs,batch_size=4)
    path=ROOT/"ml/configs/generated"/(identifier+".json")
    write_json(path,config)
    result=train(path,identifier)
    if result.get("status")=="paused_time_window":
        return result
    package=export(ROOT/"experiments/reports"/identifier/"result.json",identifier)
    return {"status":"synthetic_smoke_only","release":str(package),"verification":verify(package),"benchmark":benchmark(package)}
