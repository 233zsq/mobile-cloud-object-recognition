"""Read-only public HTTPS smoke checks, always with certificate verification."""
import argparse
import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='https://49.232.195.47:8443')
parser.add_argument('--ca',type=Path,help='Optional private CA; defaults to system trust store')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
context=ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
checks={}
with opener.open(args.url+'/health',timeout=10) as response:
    checks['health']=response.status==200 and json.load(response)['service']=='campus-review'
with opener.open(args.url+'/login',timeout=10) as response:
    checks['login_page']=response.status==200 and '登录审核工作台' in response.read().decode()
    cookie=response.headers.get('Set-Cookie','')
    checks['secure_session_cookie']=all(part in cookie for part in ('Secure','HttpOnly','SameSite=Lax'))
    checks['security_headers']=response.headers.get('X-Content-Type-Options')=='nosniff' and response.headers.get('X-Frame-Options')=='DENY'
with opener.open(args.url+'/',timeout=10) as response:
    checks['unauthenticated_redirect']=response.url==args.url+'/login'
try:
    opener.open(urllib.request.Request(args.url+'/invites',data=b'',method='POST'),timeout=10)
    checks['csrf_rejected']=False
except urllib.error.HTTPError as error:
    checks['csrf_rejected']=error.code==400
report={'at':datetime.now(timezone.utc).isoformat(),'url':args.url,'tls_certificate_validation':True,
        'checks':checks,'passed':all(checks.values()),'probe_photos_uploaded':0,'probe_accounts_created':0}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_bytes((json.dumps(report,indent=2)+'\n').encode('utf-8'))
print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
