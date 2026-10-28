"""Fetch or verify the pinned, original third-party inputs in downloads/."""
import argparse
import hashlib
import json
import urllib.request
import uuid
from pathlib import Path
from desktop_paths import resource_root, download_root

ROOT=resource_root()

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def fetch_entries(entries, folder=None, progress=None, proxy=None, verify_only=False):
    folder=Path(folder) if folder else download_root()
    folder.mkdir(parents=True,exist_ok=True)
    progress=progress or (lambda text: print(text,flush=True))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy,'http':proxy}) if proxy else urllib.request.ProxyHandler())
    for item in entries:
        assert Path(item['file']).name==item['file'] and item['file'] not in ('.','..')
        path=folder/item['file']
        assert not path.is_symlink()
        if not path.exists():
            if verify_only:
                raise FileNotFoundError('Missing: '+item['file'])
            progress('下载 '+item['file'])
            temporary=folder/(item['file']+'.'+uuid.uuid4().hex[:8]+'.partial')
            with opener.open(item['url'],timeout=45) as response,temporary.open('xb') as f:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    f.write(chunk)
            assert sha(temporary)==item['sha256'],'Downloaded hash mismatch; partial retained'
            temporary.rename(path)
        progress('校验 '+item['file'])
        assert sha(path)==item['sha256'],'Existing input hash mismatch: '+item['file']
    return folder


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify-only',action='store_true')
    p.add_argument('--with-usb-drivers',action='store_true',help='Also fetch the optional verified Windows USB driver archive')
    p.add_argument('--proxy',help='Optional explicit HTTP proxy URL')
    args=p.parse_args()
    folder=download_root();folder.mkdir(parents=True,exist_ok=True)
    entries=json.loads((ROOT/'materials/sources.json').read_text())['verified_inputs']
    if args.with_usb_drivers:
        entries += json.loads((ROOT/'materials/usb-drivers.json').read_text())['parts']
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':args.proxy}) if args.proxy else urllib.request.ProxyHandler())
    missing=[]
    for item in entries:
        path=folder/item['file']
        if not path.exists():
            if args.verify_only:
                missing.append(item['file']);continue
            temporary=folder/(item['file']+'.'+uuid.uuid4().hex[:8]+'.partial')
            print('Downloading '+item['file'],flush=True)
            with opener.open(item['url'],timeout=30) as response,temporary.open('xb') as f:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    f.write(chunk)
            assert sha(temporary)==item['sha256'],'Downloaded hash mismatch; partial retained for inspection'
            temporary.rename(path)
        assert sha(path)==item['sha256'],'Existing input hash mismatch: '+item['file']
        print('Verified '+item['file'])
    if missing: raise SystemExit('Missing: '+', '.join(missing))

if __name__=='__main__':main()
