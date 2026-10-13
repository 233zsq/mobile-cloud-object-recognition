"""Stage a new approved model directory; never overwrite an installed package."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import subprocess
import tarfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--sha256',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise PermissionError('Run with sudo')
    archive=args.archive.resolve(strict=True)
    if archive.parent!=Path('/home/ubuntu') or archive.stat().st_size>60*1024*1024 or hashlib.sha256(archive.read_bytes()).hexdigest()!=args.sha256:
        raise ValueError('Unexpected upload or changed bytes')
    root=Path('/home/gongyi/apps/mobile-cloud-backend/models/campus-evolve-v3-backend')
    with tarfile.open(archive) as source:
        members=source.getmembers()
        if sum(m.size for m in members)>100*1024*1024 or any(not m.isfile() or PurePosixPath(m.name).is_absolute() or '..' in PurePosixPath(m.name).parts for m in members):
            raise ValueError('Invalid package archive')
        root.mkdir(mode=0o750)
        source.extractall(root,filter='data')
    gid=pwd.getpwnam('gongyi').pw_gid
    for path in [root,*root.rglob('*')]:
        if path.is_symlink():
            raise ValueError('Model package must not contain symlinks')
        os.chown(path,0,gid); path.chmod(0o750 if path.is_dir() else 0o640)
    python=root.parent/'campus-gpu-v1-backend/.venv/bin/python'
    result=subprocess.run([str(python),'-B',str(root/'verify_package.py')],capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError('Staged package failed integrity verification')
    print(json.dumps({'staged':str(root),'verification':json.loads(result.stdout)}))


if __name__=='__main__':
    main()
