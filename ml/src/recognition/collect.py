"""Bounded official-API collection; downloaded labels require visual review."""
import csv
from contextlib import contextmanager
import html
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .common import ROOT, FIELDS, categories, digest, now, read_csv, read_json, write_csv, write_json

UA = "CampusRecognitionCourse/0.1 (educational image classification; source attribution retained)"
API = "https://commons.wikimedia.org/w/api.php"
SOURCES = {
    "cup": (["Mugs", "Drinking glasses", "Cups"], ['"drinking cup"', '"coffee mug"']),
    "umbrella": (["Folded umbrellas", "Closed umbrellas", "Umbrellas"], ['"umbrella"']),
    "book": (["Books on tables", "Open books", "Bookbindings"], ['intitle:"book" "on table"', 'intitle:"book" "hardcover"']),
    "pencil_case": (["Pen and pencil cases"], ['"pencil case"', '"pencil pouch"']),
    "mouse": (["Computer mice"], ['"computer mouse"']),
    "keyboard": (["Computer keyboards"], ['"computer keyboard"']),
    "earphones": (["In-ear headphones", "Wireless earbuds", "Headphones"], ['"earbuds"', '"headphones"']),
    "charger": (["Power adapters", "USB chargers", "Laptop power adapters", "Mobile phone chargers"], ['"USB charger"', '"laptop power adapter"', '"mobile phone charger"']),
    "key": (["Keys on key rings", "Keys"], ['"door key"', '"car key"']),
    "backpack": (["Backpacks"], ['"backpack"']),
}
MIDS = {"cup": "/m/02jvh9", "umbrella": "/m/0hnnb", "book": "/m/0bt_c3", "pencil_case": "/m/05676x", "mouse": "/m/020lf", "keyboard": "/m/01m2v", "earphones": "/m/01b7fy", "backpack": "/m/01940j"}
INDEX_BUDGET = int(1.2 * 1024**3)
INDEX_CHUNK_BYTES = 1024**2


@contextmanager
def quota_lock():
    """Cross-provider quota is atomic even when collection processes overlap."""
    import os
    path=ROOT/"data/raw/.collection-quota.lock"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell()==0:
            stream.write(b"0");stream.flush()
        stream.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=="nt":
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def store_download(path,blob,key):
    with quota_lock():
        count=sum(1 for provider in ("commons","openimages") for p in (ROOT/"data/raw"/provider/key).glob("*") if p.is_file())
        total=sum(p.stat().st_size for provider in ("commons","openimages") for p in (ROOT/"data/raw"/provider).rglob("*") if p.is_file())
        previous=path.stat().st_size if path.exists() else 0
        if (count>=240 and not path.exists()) or total-previous+len(blob)>3*1024**3:
            raise ValueError("Global public-photo quota reached (240 per class / 3 GiB)")
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(blob)


def index_ledger(cache):
    """Load under quota_lock; account for an older completed train scan once."""
    path=cache/'budget.json'
    ledger=read_json(path) if path.exists() else {'bytes':0,'files':{}}
    ledger.setdefault('legacy_train_scan_bytes',0)
    ledger.setdefault('train_scan_bytes',0)
    ledger.setdefault('uncertain_bytes',0)
    legacy=read_json(cache/'scan.json')['bytes'] if (cache/'scan.json').exists() else 0
    missing=max(0,legacy-ledger['legacy_train_scan_bytes']-ledger['train_scan_bytes'])
    ledger['bytes']+=missing
    ledger['legacy_train_scan_bytes']+=missing
    return ledger


def ensure_index_budget(cache):
    with quota_lock():
        ledger=index_ledger(cache)
        write_json(cache/'budget.json',ledger)
        if ledger['bytes']>=INDEX_BUDGET:
            raise ValueError('Cumulative Open Images index budget exceeded')


def index_chunks(response,cache,*,train=False,file_limit=None):
    """Charge bounded reads durably before IO; reconcile successful reads."""
    length=response.headers.get('Content-Length')
    length=int(length) if length is not None else None
    received=0
    while length is None or received<length:
        with quota_lock():
            ledger=index_ledger(cache)
            remaining=INDEX_BUDGET-ledger['bytes']
            if remaining<=0 or (file_limit is not None and received>=file_limit) or (length is not None and (length-received>remaining or (file_limit is not None and length>file_limit))):
                raise ValueError('Cumulative Open Images index budget exceeded')
            size=min(INDEX_CHUNK_BYTES,remaining)
            if length is not None:size=min(size,length-received)
            if file_limit is not None:size=min(size,file_limit-received)
            # A process killed during read cannot report its partial body.
            # Its outstanding reservation remains charged, capped at one chunk.
            ledger['bytes']+=size
            ledger['uncertain_bytes']+=size
            if train:ledger['train_scan_bytes']+=size
            write_json(cache/'budget.json',ledger)
            chunk=response.read(size)
            if len(chunk)>size:
                raise ValueError('Index response exceeded bounded read size')
            unused=size-len(chunk)
            ledger['bytes']-=unused
            ledger['uncertain_bytes']-=size
            if train:ledger['train_scan_bytes']-=unused
            write_json(cache/'budget.json',ledger)
        if not chunk:
            if length is not None and received<length:
                raise ValueError('Index response ended before Content-Length')
            return
        received+=len(chunk)
        yield chunk


def fetch(url, limit, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise ValueError("Response exceeds byte limit")
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("Response exceeds byte limit")
                return data
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            time.sleep(min(60, int(exc.headers.get("Retry-After", 2 ** (attempt+1)))))
        except (TimeoutError, urllib.error.URLError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt+1))


def api(params):
    time.sleep(.5)
    result = json.loads(fetch(API + "?" + urllib.parse.urlencode({"format": "json", "maxlag": 5, **params}), 10 * 1024**2))
    if "error" in result:
        raise ValueError(str(result["error"]))
    return result


def candidates(key, max_candidates=400):
    names, searches = SOURCES[key]
    titles = {}
    for name in names:
        continuation = {}
        while len(titles) < max_candidates:
            result = api({"action": "query", "list": "categorymembers", "cmtitle": "Category:" + name, "cmtype": "file", "cmlimit": 50, **continuation})
            for item in result.get("query", {}).get("categorymembers", []):
                titles[item["pageid"]] = item["title"]
            if "continue" not in result:
                break
            continuation = result["continue"]
    for term in searches:
        continuation = {}
        while len(titles) < max_candidates:
            result = api({"action": "query", "list": "search", "srsearch": term + " filetype:bitmap", "srnamespace": 6, "srlimit": 50, **continuation})
            for item in result.get("query", {}).get("search", []):
                titles[item["pageid"]] = item["title"]
            if "continue" not in result:
                break
            continuation = result["continue"]
    ids = list(titles)[:max_candidates]
    for start in range(0, len(ids), 10):
        result = api({"action": "query", "pageids": "|".join(map(str, ids[start:start+10])), "prop": "imageinfo", "iiprop": "url|size|mime|sha1|timestamp|extmetadata", "iiurlwidth": 960})
        for page in result.get("query", {}).get("pages", {}).values():
            info = page.get("imageinfo", [{}])[0]
            if info.get("mime") not in ("image/jpeg", "image/png", "image/webp") or min(info.get("width", 0), info.get("height", 0)) < 256:
                continue
            # Choose a standard size strictly below the original width so
            # imageinfo cannot return an unscaled original that hits the CDN limit.
            width=next(size for size in (960,500,330,250) if size<info["width"])
            if width!=960:
                resized=api({"action":"query","pageids":str(page["pageid"]),"prop":"imageinfo","iiprop":"url|size|mime|sha1|timestamp|extmetadata","iiurlwidth":width})
                info=resized["query"]["pages"][str(page["pageid"])]["imageinfo"][0]
            info["requested_thumbnail_width"]=width
            if min(info.get("thumbwidth",info["width"]),info.get("thumbheight",info["height"]))<128:
                continue
            title=page.get("title","").lower()
            description=clean(info.get("extmetadata",{}).get("ImageDescription",{}).get("value","")).lower()
            if key=="charger" and any(term in title+" "+description for term in ("charging station","charging kiosk","vending machine","electric vehicle","car battery")):
                continue
            if key=="book" and any(term in title for term in ("title page","titlepage","scanned page","book cover","front cover")):
                continue
            yield page["pageid"], page["title"], info


def clean(value):
    return html.unescape(re.sub("<[^>]+>", "", value)).strip()


def collect_commons(keys=None, per_class=120):
    from PIL import Image
    if not 1 <= per_class <= 240:
        raise ValueError("per-class must be 1..240")
    manifest = ROOT / "data/manifests/public-candidates.csv"
    rows = read_csv(manifest) if manifest.exists() else []
    seen = {r["sample_id"] for r in rows}
    budget = sum(p.stat().st_size for provider in ("commons","openimages") for p in (ROOT/"data/raw"/provider).rglob("*") if p.is_file())
    errors = []
    ordered = ["pencil_case", "charger", "earphones", "key", "cup", "umbrella", "book", "mouse", "keyboard", "backpack"]
    mapping = {c["label_key"]: c["id"] for c in categories()["categories"]}
    for key in keys or ordered:
        count = sum(r["category_id"] == str(mapping[key]) for r in rows)
        if count >= per_class:
            print(f"{key}: already {count}, skipping network",flush=True)
            continue
        try:
            for pageid, title, info in candidates(key,max_candidates=min(400,max(100,per_class*2))):
                total_class=sum(1 for provider in ("commons","openimages") for p in (ROOT/"data/raw"/provider/key).glob("*") if p.is_file())
                if count >= per_class or total_class>=240 or budget >= 3 * 1024**3:
                    break
                sid = f"commons-{pageid}"
                if sid in seen:
                    continue
                meta = info.get("extmetadata", {})
                license_name = clean(meta.get("LicenseShortName", {}).get("value", ""))
                if not license_name:
                    continue
                url = info.get("thumburl", info["url"])
                try:
                    blob = fetch(url, min(2 * 1024**2, 3 * 1024**3 - budget))
                    with Image.open(io.BytesIO(blob)) as im:
                        im.verify()
                    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
                    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                        suffix = ".jpg"
                    path = ROOT / "data/raw/commons" / key / (sid + suffix)
                    store_download(path,blob,key)
                    row = {k: "" for k in FIELDS}
                    row.update(sample_id=sid, image_path=path.relative_to(ROOT).as_posix(), image_sha256=digest(path), category_id=str(mapping[key]), collector="commons-api", captured_at="", review_status="pending", source_dataset="wikimedia_commons", source_id=str(pageid), source_url=info.get("descriptionurl", "https://commons.wikimedia.org/wiki/"+urllib.parse.quote(title)), original_url=info["url"], download_url=url, author=clean(meta.get("Artist", {}).get("value", "")), license=license_name, license_url=meta.get("LicenseUrl", {}).get("value", ""), group_id=sid, width=str(info["width"]), height=str(info["height"]))
                    row.update(downloaded_at=now(),source_version="Commons file timestamp="+info.get("timestamp","")+"; source sha1="+info.get("sha1","")+"; requested thumbnail="+str(info["requested_thumbnail_width"])+"px")
                    rows.append(row)
                    seen.add(sid)
                    budget += len(blob)
                    count += 1
                    write_csv(manifest, rows)
                    if count % 10 == 0:
                        print(f"{key}: {count}/{per_class}", flush=True)
                except Exception as exc:
                    errors.append({"category": key, "source": url, "error": str(exc)})
                    if len(errors)%5==0:
                        print(f"{key}: download skipped: {str(exc)[:160]}",flush=True)
        except Exception as exc:
            errors.append({"category": key, "error": str(exc)})
        print(f"{key}: downloaded {count}; still requires visual review", flush=True)
        write_json(ROOT/"experiments/reports/collection-status.json", {"at":now(),"bytes":budget,"counts":{k:sum(r["category_id"]==str(v) for r in rows) for k,v in mapping.items()},"errors":errors,"status":"candidate_only; collection in progress"})
    write_json(ROOT / "experiments/reports/collection-status.json", {"at": now(), "bytes": budget, "counts": {k: sum(r["category_id"] == str(v) for r in rows) for k,v in mapping.items()}, "errors": errors, "status": "candidate_only"})
    return rows


def collect_openimages(keys, per_class=120, source_split="validation"):
    """Scan only the bounded boxable label/metadata subset; no bbox archive."""
    from PIL import Image
    if any(k not in MIDS for k in keys) or not 1 <= per_class <= 240:
        raise ValueError("Open Images fallback supports only the eight boxable categories, cap 240")
    if source_split in ("validation","public-test"):
        return collect_openimages_validation(keys, per_class, source_split)
    if source_split!="train":
        raise ValueError("Unknown public source split")
    if (ROOT/"data/raw/openimages-index/scan.json").exists():
        raise ValueError("The train index was already scanned; use cached validation subset to stay within the cumulative 1.2 GiB index budget")
    manifest = ROOT / "data/manifests/openimages-candidates.csv"
    rows = read_csv(manifest) if manifest.exists() else []
    cache = ROOT / "data/raw/openimages-index"
    cache.mkdir(parents=True, exist_ok=True)
    ensure_index_budget(cache)
    selected = {}
    index_bytes = 0
    streams = ["https://storage.googleapis.com/openimages/v5/train-annotations-human-imagelabels-boxable.csv", "https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv"]
    needed = {MIDS[k]: k for k in keys}
    counts = {k: 0 for k in keys}
    for index, url in enumerate(streams):
        print("Scanning official index", url, flush=True)
        ensure_index_budget(cache)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as response:
            def lines():
                nonlocal index_bytes
                pending=b''
                for chunk in index_chunks(response,cache,train=True):
                    index_bytes+=len(chunk)
                    parts=(pending+chunk).split(b'\n')
                    pending=parts.pop()
                    for line in parts:
                        yield (line+b'\n').decode('utf-8-sig')
                if pending:yield pending.decode('utf-8-sig')
            for item in csv.DictReader(lines()):
                if index == 0:
                    key = needed.get(item.get("LabelName"))
                    if key and item.get("Confidence") == "1" and counts[key] < per_class and item["ImageID"] not in selected:
                        selected[item["ImageID"]] = key
                        counts[key] += 1
                elif item["ImageID"] in selected:
                    key = selected[item["ImageID"]]
                    sid = "oi-" + item["ImageID"]
                    if any(r["sample_id"] == sid for r in rows):
                        continue
                    path = ROOT / "data/raw/openimages" / key / (sid + ".jpg")
                    url_image = f"https://open-images-dataset.s3.amazonaws.com/train/{item['ImageID']}.jpg"
                    try:
                        budget = sum(p.stat().st_size for p in (ROOT / "data/raw").rglob("*") if p.is_file())
                        blob = fetch(url_image, min(2*1024**2, 3*1024**3-budget))
                        with Image.open(io.BytesIO(blob)) as im:
                            im.verify()
                        store_download(path,blob,key)
                        row = {k: "" for k in FIELDS}
                        category = next(c["id"] for c in categories()["categories"] if c["label_key"] == key)
                        row.update(sample_id=sid, image_path=path.relative_to(ROOT).as_posix(), image_sha256=digest(path), category_id=str(category), source_dataset="open_images", source_id=item["ImageID"], source_url=item.get("OriginalLandingURL", ""), original_url=item.get("OriginalURL", ""), download_url=url_image, author=item.get("Author", ""), license=item.get("License", ""), collector="open-images-official", review_status="pending", group_id=sid)
                        rows.append(row)
                        write_csv(manifest, rows)
                    except Exception as exc:
                        print(f"{sid}: {exc}", flush=True)
    with quota_lock():
        ledger=index_ledger(cache)
        write_json(cache / "scan.json", {"at": now(), "bytes": index_bytes, "index_bytes_cumulative":ledger['bytes'], "keys": keys, "selected": selected})
    return rows


def collect_openimages_validation(keys, per_class, source_split="validation"):
    """Cache small official indexes once; these are public training sources here."""
    from PIL import Image
    cache=ROOT/"data/raw/openimages-index"
    cache.mkdir(parents=True,exist_ok=True)
    ledger_path=cache/"budget.json"
    subset="test" if source_split=="public-test" else "validation"
    urls={
        f"{subset}-labels.csv":f"https://storage.googleapis.com/openimages/v5/{subset}-annotations-human-imagelabels-boxable.csv",
        f"{subset}-images.csv":f"https://storage.googleapis.com/openimages/2018_04/{subset}/{subset}-images-with-rotation.csv",
    }
    if subset=="test":
        urls["test-boxes.csv"]="https://storage.googleapis.com/openimages/v5/test-annotations-bbox.csv"
    for name,url in urls.items():
        path=cache/name
        with quota_lock():
            ledger=index_ledger(cache)
        previous=ledger["files"].get(name)
        if previous and path.exists() and digest(path)==previous["sha256"]:
            continue
        # A failed download consumes budget too; charge every received chunk.
        print(f"Caching bounded official index {name}",flush=True)
        ensure_index_budget(cache)
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=60) as response:
            tmp=path.with_suffix(".partial")
            try:
                with tmp.open("wb") as output:
                    for chunk in index_chunks(response,cache,file_limit=90*1024**2):
                        output.write(chunk)
                tmp.replace(path)
            finally:
                if tmp.exists():
                    tmp.unlink()
        with quota_lock():
            ledger=index_ledger(cache)
            ledger["files"][name]={"url":url,"sha256":digest(path),"bytes":path.stat().st_size,"downloaded_at":now()}
            write_json(ledger_path,ledger)
    positive={}
    reverse={v:k for k,v in MIDS.items()}
    with (cache/f"{subset}-labels.csv").open(encoding="utf-8-sig",newline="") as f:
        for item in csv.DictReader(f):
            if item.get("Confidence")=="1" and item["LabelName"] in reverse:
                positive.setdefault(item["ImageID"],set()).add(reverse[item["LabelName"]])
    dominant=None
    if subset=="test":
        boxes={}
        with (cache/"test-boxes.csv").open(encoding="utf-8-sig",newline="") as f:
            for item in csv.DictReader(f):
                key=reverse.get(item["LabelName"])
                if key:
                    boxes.setdefault((item["ImageID"],key),[]).append(item)
        dominant=set()
        for (sid,key),items in boxes.items():
            if len(items)!=1:
                continue
            box=items[0]
            area=(float(box["XMax"])-float(box["XMin"]))*(float(box["YMax"])-float(box["YMin"]))
            if area>=.25 and all(box.get(flag,"0")=="0" for flag in ("IsGroupOf","IsDepiction","IsTruncated")):
                dominant.add((sid,key))
    manifest=ROOT/"data/manifests/openimages-candidates.csv"
    rows=read_csv(manifest) if manifest.exists() else []
    seen={r["sample_id"] for r in rows}
    mapping={c["label_key"]:c["id"] for c in categories()["categories"]}
    counts={k:sum(r["category_id"]==str(mapping[k]) for r in rows) for k in keys}
    with (cache/f"{subset}-images.csv").open(encoding="utf-8-sig",newline="") as f:
        for item in csv.DictReader(f):
            labels=positive.get(item["ImageID"],set())
            # Do not introduce ambiguous labels among our ten target categories.
            if len(labels)!=1:
                continue
            key=next(iter(labels))
            if dominant is not None and (item["ImageID"],key) not in dominant:
                continue
            if key not in keys or counts[key]>=per_class:
                continue
            sid="oi-"+item["ImageID"]
            if sid in seen:
                continue
            url=f"https://open-images-dataset.s3.amazonaws.com/{subset}/{item['ImageID']}.jpg"
            try:
                blob=fetch(url,2*1024**2)
                with Image.open(io.BytesIO(blob)) as im:
                    im.verify()
                path=ROOT/"data/raw/openimages"/key/(sid+".jpg")
                store_download(path,blob,key)
                row={k:"" for k in FIELDS}
                row.update(sample_id=sid,image_path=path.relative_to(ROOT).as_posix(),image_sha256=digest(path),category_id=str(mapping[key]),source_dataset="open_images",source_id=item["ImageID"],source_url=item.get("OriginalLandingURL",""),original_url=item.get("OriginalURL",""),download_url=url,author=item.get("Author",""),license=item.get("License",""),license_url=item.get("License",""),collector="open-images-official",review_status="pending",group_id=sid,downloaded_at=now(),source_version=f"Open Images V7 public {subset} image / V5 human boxable labels"+("; one non-depicted box >=25% image area" if dominant is not None else ""))
                rows.append(row);seen.add(sid);counts[key]+=1
                write_csv(manifest,rows)
                if counts[key]%10==0:
                    print(f"{key}: {counts[key]}/{per_class}",flush=True)
            except Exception as exc:
                print(f"{sid}: {exc}",flush=True)
                if "quota reached" in str(exc):
                    counts[key]=per_class
    with quota_lock():
        ledger=index_ledger(cache)
    write_json(ROOT/"experiments/reports/openimages-collection-status.json",{"at":now(),"source_split":source_split,"project_final_test_used":False,"index_bytes_cumulative":ledger["bytes"],"counts":{k:sum(r["category_id"]==str(mapping[k]) for r in rows) for k in keys},"status":"requires_visual_review"})
    return rows
