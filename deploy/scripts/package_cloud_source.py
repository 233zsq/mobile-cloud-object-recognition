"""Archive fixed public deployment sources only, including their exact revision."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision',default='HEAD')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
revision=subprocess.check_output(['git','rev-parse','--verify',args.revision+'^{commit}'],cwd=root,text=True).strip()
blob=subprocess.check_output(['git','archive',revision,'backend','database','deploy','web'],cwd=root)
with tarfile.open(fileobj=io.BytesIO(blob)) as source, tarfile.open(args.output,'x') as destination:
    for member in source:
        if member.isfile() and not any(part.startswith('.') for part in Path(member.name).parts):
            destination.addfile(member,source.extractfile(member))
    data=(revision+'\n').encode()
    entry=tarfile.TarInfo('SOURCE_REVISION'); entry.size=len(data)
    destination.addfile(entry,io.BytesIO(data))
print(revision,hashlib.sha256(args.output.read_bytes()).hexdigest())
