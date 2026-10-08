"""Reviewable manifests and leakage-resistant immutable splits."""
from collections import Counter
import math
import random
import shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageFont
from .common import ROOT, categories, category_path, digest, image_path, now, read_csv, read_json, safe_name, write_csv, write_json


def phash(im):
    a = np.asarray(ImageOps.exif_transpose(im).convert("L").resize((32,32)), dtype=float)
    k, n = np.arange(8)[:,None], np.arange(32)[None,:]
    matrix = np.cos(np.pi * (n+.5) * k / 32)
    low = matrix @ a @ matrix.T
    bits = (low > np.median(low.ravel()[1:])).ravel()
    return f"{sum(int(bit) << i for i,bit in enumerate(bits)):016x}"


def validate_field_rows(rows):
    if any(r['review_status']!='approved' or r.get('source_dataset') not in ('field','self_captured') or not r.get('object_id') or not r.get('session_id') for r in rows):
        raise ValueError('Approved field photos with real object IDs and session IDs required')
    if any(int(r['category_id']) not in range(10) for r in rows):
        raise ValueError('Field category outside 0..9')
    if any(sum(int(r['category_id'])==i for r in rows)<20 for i in range(10)):
        raise ValueError('Need at least twenty field photos per class')
    if len({r['sample_id'] for r in rows})!=len(rows) or len({r['image_sha256'] for r in rows})!=len(rows):
        raise ValueError('Duplicate field test sample ID or image SHA-256')


def audit(manifest, decisions=None, contact_sheets=True):
    rows = read_csv(manifest)
    choices = {r["sample_id"]: r for r in read_csv(decisions)} if decisions else {}
    unknown=set(choices)-{r["sample_id"] for r in rows}
    if unknown:
        raise ValueError(f"Review decisions reference unknown samples: {sorted(unknown)}")
    if len({r["sample_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate sample_id")
    parents = {r["sample_id"]: r["sample_id"] for r in rows}
    def find(v):
        while parents[v] != v:
            parents[v] = parents[parents[v]]
            v = parents[v]
        return v
    def union(a,b):
        a,b = find(a),find(b)
        if a != b:
            parents[max(a,b)] = min(a,b)
    identities = {}
    valid = []
    for row in rows:
        choice=choices.get(row["sample_id"])
        if choice:
            for field in ("group_id","object_id"):
                if choice.get(field):
                    row[field]=choice[field]
        reason = ""
        try:
            if int(row["category_id"]) not in range(10):
                raise ValueError("invalid category")
            path = image_path(row["image_path"])
            actual = digest(path)
            if row.get("image_sha256") and row["image_sha256"] != actual:
                raise ValueError("image hash changed")
            row["image_sha256"] = actual
            with Image.open(path) as im:
                im.load()
                corrected = ImageOps.exif_transpose(im)
                row["width"],row["height"] = map(str,corrected.size)
                if min(corrected.size) < 128:
                    reason = "too_small"
                row["phash"] = phash(im)
            valid.append(row)
            identity_keys = ["sha:"+actual]
            for key in ("object_id", "group_id", "original_url"):
                if row.get(key):
                    identity_keys.append(key+":"+row[key])
            for key in identity_keys:
                if key in identities:
                    union(row["sample_id"], identities[key])
                identities[key] = row["sample_id"]
        except Exception as exc:
            reason = "invalid_image: " + str(exc)
        choice = choices.get(row["sample_id"])
        if choice:
            if choice.get("review_status") not in ("approved", "rejected", "pending"):
                raise ValueError("Review decisions must be approved/rejected/pending")
            row["review_status"] = choice["review_status"]
            row["review_reason"] = choice.get("review_reason", "")
            if choice.get("category_id"):
                if int(choice["category_id"]) not in range(10):
                    raise ValueError("Review category outside 0..9")
                row["category_id"] = choice["category_id"]
        if reason:
            row["review_status"] = "rejected"
            row["review_reason"] = reason
    for i,a in enumerate(valid):
        for b in valid[:i]:
            if (int(a["phash"],16) ^ int(b["phash"],16)).bit_count() <= 6:
                union(a["sample_id"], b["sample_id"])
    group_labels = {}
    for row in rows:
        row["group_id"] = find(row["sample_id"])
        if row["review_status"] == "approved":
            group_labels.setdefault(row["group_id"],set()).add(row["category_id"])
    for row in rows:
        if len(group_labels.get(row["group_id"],[])) > 1:
            row["review_status"] = "pending"
            row["review_reason"] = "group_label_conflict; requires relabel/reject"
    unique_hashes={}
    for row in rows:
        if row["review_status"]=="approved":
            if row["image_sha256"] in unique_hashes:
                row["review_status"]="rejected"
                row["review_reason"]="exact_duplicate_of:"+unique_hashes[row["image_sha256"]]
            else:
                unique_hashes[row["image_sha256"]]=row["sample_id"]
    write_csv(manifest,rows)
    report = ROOT / "experiments/reports/audit"
    write_json(report / "summary.json", {"at":now(),"manifest_sha256":digest(manifest),"review_counts":dict(Counter(r["review_status"] for r in rows)),"approved_by_class":dict(Counter(r["category_id"] for r in rows if r["review_status"] == "approved")),"groups":len(set(r["group_id"] for r in rows))})
    if contact_sheets:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf",14) if Path("C:/Windows/Fonts/arial.ttf").exists() else ImageFont.load_default()
        for category in range(10):
            subset = [r for r in rows if int(r["category_id"]) == category]
            for start in range(0,len(subset),20):
                sheet = Image.new("RGB",(1000,900),"white")
                draw = ImageDraw.Draw(sheet)
                for i,row in enumerate(subset[start:start+20]):
                    x,y=(i%5)*200,(i//5)*225
                    try:
                        with Image.open(image_path(row["image_path"])) as im:
                            thumb=ImageOps.exif_transpose(im).convert("RGB")
                            thumb.thumbnail((190,175))
                            sheet.paste(thumb,(x+(190-thumb.width)//2,y))
                    except Exception:
                        pass
                    draw.text((x+3,y+177),row["sample_id"],fill="black",font=font)
                    draw.text((x+3,y+196),row["review_status"],fill="black",font=font)
                report.mkdir(parents=True,exist_ok=True)
                sheet.save(report / f"class-{category}-{start//20+1:02}.png")
    return rows


def connected_groups(rows):
    """Keep every object identity and audited group connection in one component."""
    identities=[]
    by_identity={}
    for index,row in enumerate(rows):
        keys=[(field,row[field]) for field in ('object_id','group_id') if row.get(field)]
        if not keys:
            raise ValueError('Every sample needs object_id or audited group_id')
        identities.append(keys)
        for key in keys:
            by_identity.setdefault(key,[]).append(index)
    visited=set()
    groups=[]
    for start in range(len(rows)):
        if start in visited:
            continue
        pending=[start]
        members=[]
        while pending:
            index=pending.pop()
            if index in visited:
                continue
            visited.add(index)
            members.append(index)
            for key in identities[index]:
                pending.extend(by_identity.pop(key,()))
        groups.append([rows[index].copy() for index in sorted(members)])
    return groups


def freeze_split(manifest, version, seed=42, test_manifest=None):
    safe_name(version)
    directory=ROOT / "data/splits" / version
    if directory.exists():
        raise ValueError("Data version exists; create a new immutable version")
    approved=[r for r in read_csv(manifest) if r["review_status"] == "approved"]
    if len({r["image_sha256"] for r in approved})!=len(approved):
        raise ValueError("Exact duplicates must be removed by audit before freezing")
    if any(r.get("source_dataset")=="synthetic_smoke" for r in approved):
        raise ValueError("Synthetic fixtures must stay in explicitly marked smoke datasets")
    if {int(r["category_id"]) for r in approved} != set(range(10)):
        raise ValueError("Need approved samples in all ten categories")
    rng=random.Random(seed)
    train,val=[],[]
    grouped=connected_groups(approved)
    if any(len({r["category_id"] for r in group}) != 1 for group in grouped):
        raise ValueError("Group contains conflicting category labels")
    for category in range(10):
        groups=[group for group in grouped if int(group[0]["category_id"]) == category]
        if len(groups)<2:
            raise ValueError(f"Class {category} requires at least two independent groups")
        rng.shuffle(groups)
        target=sum(len(g) for g in groups)*.25
        validation=[]
        for group in groups[:-1]:
            if not validation or abs(len(validation)+len(group)-target)<abs(len(validation)-target):
                validation.extend(group)
            else:
                train.extend(group)
        train.extend(groups[-1])
        val.extend(validation)
    tests=[]
    if test_manifest:
        tests=read_csv(test_manifest)
        validate_field_rows(tests)
    check_isolation(train,val,tests)
    category=categories()
    meta={"status":"frozen","data_version":version,"category_version":category["category_version"],"categories_sha256":digest(ROOT/"shared/categories.json"),"created_at":now(),"seed":seed,"grouping":"connected components of namespaced object_id and audited group_id identities", "files":{}, "source_manifest_sha256":digest(manifest),"final_test_status":"frozen" if tests else "pending_field_photos"}
    # Check all bytes before creating a version so an invalid sample cannot half-freeze it.
    for row in train+val+tests:
        if digest(image_path(row["image_path"])) != row["image_sha256"]:
            raise ValueError("Image hash differs from approved manifest")
    directory.mkdir(parents=True)
    source_snapshot=directory/"audited-source.csv"
    shutil.copyfile(manifest,source_snapshot)
    if digest(source_snapshot)!=meta["source_manifest_sha256"]:
        raise ValueError("Source manifest changed during freezing")
    meta["source_snapshot"]={"file":source_snapshot.name,"sha256":digest(source_snapshot)}
    for name,rows in (("train",train),("validation",val),("test",tests)):
        for row in rows:
            row.update(split_name=name,data_version=version)
        if name=="test" and not rows:
            continue
        path=directory / f"{name}.csv"
        write_csv(path,rows)
        meta["files"][name]={"sha256":digest(path),"count":len(rows),"counts":dict(Counter(r["category_id"] for r in rows))}
    write_json(directory/"dataset.json",meta)
    return meta


def check_isolation(*sets):
    previous=set()
    for rows in sets:
        keys=set()
        for row in rows:
            for field in ("sample_id","image_sha256","object_id","group_id","original_url"):
                if row.get(field):
                    keys.add(field+":"+row[field])
        if keys & previous:
            raise ValueError("Cross-split identity/hash/source leakage detected")
        previous |= keys
    # Conservative near-duplicate safeguard also covers field-vs-public images.
    for i,a in enumerate(sets):
        for b in sets[:i]:
            for ra in a:
                for rb in b:
                    if ra.get("phash") and rb.get("phash") and (int(ra["phash"],16)^int(rb["phash"],16)).bit_count()<=6:
                        raise ValueError("Cross-split perceptual near duplicate")


def load_split(version,name,allow_test=False):
    safe_name(version)
    if name=="test" and not allow_test:
        raise ValueError("Training and selection cannot read final test")
    if name not in ("train","validation","test"):
        raise ValueError("Unknown split")
    directory=ROOT / "data/splits" / version
    metadata=read_json(directory/"dataset.json")
    categories(metadata["category_version"])
    if metadata["status"]!="frozen" or metadata["categories_sha256"]!=digest(category_path(metadata["category_version"])):
        raise ValueError("Frozen category mapping changed")
    if metadata.get("source_snapshot") and digest(directory/metadata["source_snapshot"]["file"])!=metadata["source_snapshot"]["sha256"]:
        raise ValueError("Frozen audited-source manifest changed")
    path=directory/f"{name}.csv"
    if name not in metadata["files"] or digest(path)!=metadata["files"][name]["sha256"]:
        raise ValueError("Missing or changed frozen manifest")
    rows=read_csv(path)
    for row in rows:
        if row["split_name"]!=name or row["data_version"]!=version or row["review_status"]!="approved":
            raise ValueError("Invalid frozen split row")
        if digest(image_path(row["image_path"]))!=row["image_sha256"]:
            raise ValueError("Frozen image bytes changed")
    return rows,metadata


def freeze_field_test(manifest,version,training_version):
    """Attach an independent field-test version without touching training splits."""
    safe_name(version)
    if not training_version:
        raise ValueError("--training-version is required for --test-only")
    directory=ROOT/"data/splits"/version
    if directory.exists():
        raise ValueError("Test version exists")
    train,data=load_split(training_version,"train")
    val,_=load_split(training_version,"validation")
    rows=read_csv(manifest)
    validate_field_rows(rows)
    check_isolation(train,val,rows)
    for row in rows:
        if digest(image_path(row["image_path"]))!=row["image_sha256"]:
            raise ValueError("Field photo hash changed")
        row.update(split_name="test",data_version=version)
    path=directory/"test.csv"
    write_csv(path,rows)
    metadata={"status":"frozen","purpose":"independent_field_test","data_version":version,"training_version":training_version,"category_version":data["category_version"],"categories_sha256":data["categories_sha256"],"created_at":now(),"source_manifest_sha256":digest(manifest),"files":{"test":{"sha256":digest(path),"count":len(rows)}}}
    write_json(directory/"dataset.json",metadata)
    return metadata
