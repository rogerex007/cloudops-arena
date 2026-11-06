#!/usr/bin/env python3
"""Read-only checks after narrowing Cloudflare Access to instructor routes."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='https://arena.costacorp.net')
    args=parser.parse_args()
    base=args.base_url.rstrip('/')
    opener=build_opener(NoRedirect)
    good=True
    checks=[('/',False),('/instructor',True),('/instructor/',True),
        ('/api/v1/admin',True),('/api/v1/admin/dashboard',True),
        ('/api/v1/auth/admin',True),('/api/v1/auth/admin/login',True),
        ('/api/v1/actions/evaluations/test/test',False)]
    for path,protected in checks:
        request=Request(base+path,headers={'User-Agent':'CloudOps-Arena-Access-Check/1.0'})
        try:response=opener.open(request,timeout=15)
        except HTTPError as error:response=error
        except URLError:
            print(json.dumps({'path':path,'ok':False,'error':'connection_failed'}));good=False;continue
        with response:
            status=response.status
            content_type=response.headers.get('Content-Type','')
            target=urlsplit(response.headers.get('Location',''))
            login_redirect=status in {302,303,307,308} and target.hostname is not None and target.hostname.endswith('.cloudflareaccess.com')
            if protected:ok=login_redirect
            elif path=='/':ok=status==200 and 'text/html' in content_type
            else:ok=status==401 and 'application/json' in content_type
            print(json.dumps({'path':path,'status':status,'cloudflare_login':login_redirect,'ok':ok}))
            good=good and ok
    return 0 if good else 1


if __name__=='__main__':raise SystemExit(main())
