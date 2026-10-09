"""Command line entrypoint; runtime imports remain lazy."""
import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from .common import ROOT, categories, digest, now, write_json


def doctor():
    import os
    os.environ.setdefault("KERAS_HOME",str(ROOT/"experiments/checkpoints/keras-cache"))
    result={"at":now(),"root":str(ROOT),"python":sys.version,"platform":platform.platform(),"category_version":categories()["category_version"],"dependencies":{}}
    for name in ("tensorflow","keras","numpy","Pillow","ai-edge-litert","matplotlib","scikit-learn"):
        try:
            result["dependencies"][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["dependencies"][name]=None
    try:
        import tensorflow as tf
        result["gpu"]=[p.name for p in tf.config.list_physical_devices("GPU")]
        for gpu in tf.config.list_physical_devices("GPU"):
            tf.config.experimental.set_memory_growth(gpu,True)
        result["tensor_test"]=float(tf.reduce_sum(tf.ones((2,2))))
    except ImportError:
        result["gpu"]=[]
    write_json(ROOT/"experiments/reports/environment/doctor.json",result)
    return result


def parser():
    p=argparse.ArgumentParser(description="Campus ten-class training and model handover")
    s=p.add_subparsers(dest="command",required=True)
    a=s.add_parser("doctor")
    a.add_argument("--training-check",action="store_true")
    a.add_argument("--require-gpu",action="store_true")
    a=s.add_parser("collect")
    a.add_argument("--provider",choices=["commons","openimages"],default="commons")
    a.add_argument("--categories",nargs="+")
    a.add_argument("--per-class",type=int,default=120)
    a.add_argument("--source-split",choices=["train","validation","public-test"],default="validation",help="Open Images public source subset; unrelated to project evaluation splits")
    a=s.add_parser("audit")
    a.add_argument("--manifest",type=__import__("pathlib").Path,default=ROOT/"data/manifests/public-candidates.csv")
    a.add_argument("--decisions",type=__import__("pathlib").Path)
    a.add_argument("--merge-manifests",nargs="+",type=__import__("pathlib").Path)
    a.add_argument("--no-contact-sheets",action="store_true")
    a=s.add_parser("split")
    a.add_argument("--manifest",required=True,type=__import__("pathlib").Path)
    a.add_argument("--version",required=True)
    a.add_argument("--seed",type=int,default=42)
    a.add_argument("--test-manifest",type=__import__("pathlib").Path)
    a.add_argument("--test-only",action="store_true")
    a.add_argument("--training-version")
    a=s.add_parser("train")
    a.add_argument("--config",required=True,type=__import__("pathlib").Path)
    a.add_argument("--experiment",required=True)
    a.add_argument("--resume",action="store_true")
    a.add_argument("--initial-checkpoint",type=__import__("pathlib").Path)
    a=s.add_parser("sweep")
    a.add_argument("--config",required=True,type=__import__("pathlib").Path)
    a.add_argument("--campaign",required=True)
    a.add_argument("--stage",required=True,choices=["learning_rate","dropout","fine_tune"])
    a.add_argument("--previous",type=__import__("pathlib").Path)
    a.add_argument("--execute",action="store_true")
    a=s.add_parser("summarize")
    a.add_argument("--jobs",required=True,type=__import__("pathlib").Path)
    a=s.add_parser("reproduce")
    a.add_argument("--result",required=True,type=__import__("pathlib").Path)
    a.add_argument("--seed",type=int,choices=[43,44],default=43)
    a=s.add_parser("export")
    a.add_argument("--result",required=True,type=__import__("pathlib").Path)
    a.add_argument("--version",required=True)
    a.add_argument("--formal",action="store_true")
    a.add_argument("--reproduction",type=__import__("pathlib").Path)
    a.add_argument("--additional-reproduction",type=__import__("pathlib").Path)
    for name in ("verify","evaluate","benchmark"):
        a=s.add_parser(name)
        a.add_argument("--release",required=True,type=__import__("pathlib").Path)
        if name=="verify":
            a.add_argument("--external-report",type=__import__("pathlib").Path)
        if name=="evaluate":
            a.add_argument("--split",choices=["validation","test"],default="validation")
            a.add_argument("--test-version")
            a.add_argument("--confirm-model-hash")
        if name=="benchmark":
            a.add_argument("--threads",type=int,default=1)
            a.add_argument("--warmup",type=int,default=20)
            a.add_argument("--iterations",type=int,default=100)
    a=s.add_parser("smoke",help="Synthetic fixtures; never formal accuracy evidence")
    a.add_argument("--id",default="smoke-v1")
    a.add_argument("--epochs",type=int,default=1)
    a=s.add_parser('evolve',help='Reviewed batches and fixed-parent model comparison')
    e=a.add_subparsers(dest='action',required=True)
    a=e.add_parser('import-batch')
    a.add_argument('--archive',required=True,type=__import__('pathlib').Path)
    a.add_argument('--version',required=True)
    a.add_argument('--base-version',default='campus-public-expanded-v1')
    a.add_argument('--parent-release',default='campus-gpu-v1')
    a=e.add_parser('compare')
    a.add_argument('--release',required=True,type=__import__('pathlib').Path)
    a.add_argument('--baseline',default='campus-gpu-v1')
    a=e.add_parser('accept-approval')
    a.add_argument('--release',required=True,type=__import__('pathlib').Path)
    a.add_argument('--receipt',required=True,type=__import__('pathlib').Path)
    a.add_argument('--comparison',required=True,type=__import__('pathlib').Path)
    return p


def main():
    args=parser().parse_args()
    try:
        if args.command=="doctor":
            value=doctor()
            if args.require_gpu and not args.training_check:
                raise ValueError("--require-gpu must accompany --training-check")
            if args.training_check:
                from .training import preflight
                value["training_preflight"]=preflight(args.require_gpu)
        elif args.command=="collect":
            from .collect import collect_commons,collect_openimages
            if args.provider=="openimages" and not args.categories:
                raise ValueError("Specify only missing --categories for Open Images fallback")
            rows=collect_commons(args.categories,args.per_class) if args.provider=="commons" else collect_openimages(args.categories,args.per_class,args.source_split)
            value={"candidates":len(rows),"status":"requires_visual_review"}
        elif args.command=="audit":
            from .data import audit
            if args.merge_manifests:
                from .common import read_csv,write_csv
                combined={}
                for source in args.merge_manifests:
                    for row in read_csv(source):
                        if row["sample_id"] in combined and combined[row["sample_id"]]["category_id"]!=row["category_id"]:
                            raise ValueError("Same source sample has conflicting labels")
                        combined[row["sample_id"]]=row
                write_csv(args.manifest,list(combined.values()))
            rows=audit(args.manifest,args.decisions,not args.no_contact_sheets)
            value={"samples":len(rows),"approved":sum(r["review_status"]=="approved" for r in rows)}
        elif args.command=="split":
            from .data import freeze_split,freeze_field_test
            value=freeze_field_test(args.manifest,args.version,args.training_version) if args.test_only else freeze_split(args.manifest,args.version,args.seed,args.test_manifest)
        elif args.command=="train":
            from .training import train
            value=train(args.config,args.experiment,args.resume,args.initial_checkpoint)
        elif args.command=="sweep":
            from .training import sweep
            value=str(sweep(args.config,args.campaign,args.stage,args.previous,args.execute))
        elif args.command=="summarize":
            from .training import summarize
            value=str(summarize(args.jobs))
        elif args.command=="reproduce":
            from .training import reproduce
            value=reproduce(args.result,args.seed)
        elif args.command=="export":
            from .release import export
            value=str(export(args.result,args.version,args.formal,args.reproduction,args.additional_reproduction))
        elif args.command=="verify":
            from .release import verify
            value=verify(args.release,args.external_report)
        elif args.command=="evaluate":
            from .release import evaluate
            value=evaluate(args.release,args.split,args.test_version,args.confirm_model_hash)
        elif args.command=="benchmark":
            from .release import benchmark
            value=benchmark(args.release,args.threads,args.warmup,args.iterations)
        elif args.command=="smoke":
            from .smoke import smoke
            value=smoke(args.id,args.epochs)
        elif args.command=='evolve':
            from .evolution import import_batch,compare,accept_approval
            if args.action=='import-batch':
                value=import_batch(args.archive,args.version,args.base_version,args.parent_release)
            elif args.action=='compare':
                value=str(compare(args.release,args.baseline))
            else:
                value=accept_approval(args.release,args.receipt,args.comparison)
        print(json.dumps(value,ensure_ascii=False,indent=2,default=str))
    except (ValueError,FileNotFoundError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; resume the run from its most recent complete epoch.",file=sys.stderr)
        return 130
    return 0


if __name__=="__main__":
    sys.exit(main())
