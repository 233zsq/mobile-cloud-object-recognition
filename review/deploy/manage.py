"""Run the review admin CLI under the service's existing configuration."""
import os
import sys
from pathlib import Path

app=Path.home()/'apps/campus-review'
environment=os.environ.copy()
for line in (Path.home()/'.config/campus-review/review.env').read_text().splitlines():
    key,value=line.split('=',1)
    environment[key]=value
python=app/'venv/bin/python'
os.chdir(app/'current/review')
os.execve(python,[str(python),'-m','flask','--app','campus_review:create_app',*sys.argv[1:]],environment)
