"""Offline Windows Root kit preparation. Never connects to or flashes a phone."""
import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path
from fetch_materials import sha

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seven-zip',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'private/root-kit')
    args=p.parse_args()
    assert os.name=='nt','This preparation recipe is verified on Windows'
    assert args.seven_zip.is_file()
    source=json.loads((ROOT/'materials/sources.json').read_text())
    items={x['id']:x for x in source['verified_inputs']}
    for item in items.values():
        path=ROOT/'downloads'/item['file']
        assert path.is_file() and sha(path)==item['sha256'],'Missing or mismatched input: '+item['file']
    kit=args.output.resolve()
    assert not kit.exists(),'Output exists; use a new directory to preserve keys and images'
    kit.mkdir(parents=True)
    account=subprocess.check_output(['whoami'],text=True).strip()
    subprocess.run(['icacls',str(kit),'/inheritance:r','/grant:r',account+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,capture_output=True)
    work=kit/'autoroot';work.mkdir()
    with zipfile.ZipFile(ROOT/'downloads'/items['autoroot-v4']['file']) as z:
        for member in z.infolist():
            target=(work/member.filename).resolve()
            assert target.is_relative_to(work) and not stat.S_ISLNK(member.external_attr>>16)
        z.extractall(work)
    # Preserve AppWorld and other stock apps; use the existing minimal root helpers.
    original=(work/'patch.txt').read_text()
    patch='\n'.join(line for line in original.splitlines() if not line.startswith('removeapp ') and not line.startswith('#sys.'))+'\n'
    (work/'patch-owner.txt').write_text(patch,encoding='ascii')
    for name in ['q10_root_rsa','q10_host_rsa']:
        subprocess.run(['ssh-keygen','-q','-t','rsa','-b','3072','-m','PEM','-N','','-f',str(kit/name)],check=True)
    sshdir=work/'patchdata/var/etc/ssh'
    pub=(kit/'q10_root_rsa.pub').read_text().strip()
    (sshdir/'authorized_keys2').write_text('from="169.254.0.2",no-agent-forwarding,no-port-forwarding,no-X11-forwarding '+pub+'\n',encoding='ascii')
    shutil.copyfile(kit/'q10_host_rsa',sshdir/'ssh_host_rsa_key')
    shutil.copyfile(kit/'q10_host_rsa.pub',sshdir/'ssh_host_rsa_key.pub')
    config=(sshdir/'sshd_config').read_text()
    config=config.replace('AuthorizedKeysFile=/etc/ssh/authorized_keys2 /accounts/devuser/.ssh/authorized_keys2','AuthorizedKeysFile=/etc/ssh/authorized_keys2')
    assert 'PasswordAuthentication=no' in config
    (sshdir/'sshd_config').write_text(config,encoding='ascii')
    host=(kit/'q10_host_rsa.pub').read_text().split()
    (kit/'known_hosts').write_text('169.254.0.1 '+' '.join(host[:2])+'\n',encoding='ascii')
    (kit/'ssh_config').write_text('Host bb10-root q10-root\n    HostName 169.254.0.1\n    User root\n'
        +'    IdentityFile "'+(kit/'q10_root_rsa').as_posix()+'"\n'
        +'    UserKnownHostsFile "'+(kit/'known_hosts').as_posix()+'"\n'
        +'    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n    PasswordAuthentication no\n    BatchMode yes\n    ConnectTimeout 5\n'
        +'    Ciphers aes128-ctr,aes192-ctr,aes256-ctr\n    HostKeyAlgorithms +ssh-rsa\n    PubkeyAcceptedAlgorithms +ssh-rsa\n',encoding='utf-8')
    libusb=items['libusb']
    data=subprocess.check_output([str(args.seven_zip),'e','-so',str(ROOT/'downloads'/libusb['file']),libusb['extract']])
    assert hashlib.sha256(data).hexdigest()==libusb['dll_sha256']
    (work/'libusb-1.0.dll').write_bytes(data)
    lzo=items['lzo']
    with tarfile.open(ROOT/'downloads'/lzo['file'],mode='r:zst') as t:
        data=t.extractfile(lzo['extract']).read()
        assert hashlib.sha256(data).hexdigest()==lzo['dll_sha256']
        (work/'lzo2.dll').write_bytes(data)
        (work/'LZO-LICENSE.txt').write_bytes(t.extractfile('mingw64/share/licenses/lzo2/LICENSE').read())
    git_core=Path(subprocess.check_output(['git','--exec-path'],text=True).strip())
    for name,digest in source['openssl']['files'].items():
        data=(git_core/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==digest,'OpenSSL version/hash differs; see materials/sources.json'
        (work/name).write_bytes(data)
    license_path=git_core.parents[2]/'mingw64/share/licenses/openssl/LICENSE'
    assert license_path.is_file(),'Keep the OpenSSL license with the local DLLs'
    shutil.copyfile(license_path,work/'OPENSSL-LICENSE.txt')
    stock=kit/'stock';stock.mkdir()
    item=items['stock-q10']
    subprocess.run([str(args.seven_zip),'e','-y',str(ROOT/'downloads'/item['file']),item['extracted_file'],'-o'+str(stock)],check=True,capture_output=True)
    assert sha(stock/item['extracted_file'])==item['extracted_sha256']
    (kit/'images').mkdir()
    report={'offline_preparation_complete':True,'phone_connected_or_modified':False,
            'shared_default_ssh_authorization_replaced':True,'appworld_preserved':True,
            'stock_sha256':item['extracted_sha256'],'root_bundle_sha256':items['autoroot-v4']['sha256']}
    (kit/'preparation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'kit':str(kit),**report}))

if __name__=='__main__':main()
