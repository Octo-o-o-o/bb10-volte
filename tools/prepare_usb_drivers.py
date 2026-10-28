"""Extract and verify the pinned Windows driver package without installing it."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from fetch_materials import sha
from desktop_paths import resource_root, private_root, download_root

ROOT=resource_root()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seven-zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=private_root()/'windows-usb')
    parser.add_argument('--cache',type=Path,default=download_root())
    args=parser.parse_args(argv)
    spec=json.loads((ROOT/'materials/usb-drivers.json').read_text())
    for item in spec['parts']:
        assert sha(args.cache/item['file'])==item['sha256']
    kit=args.output.resolve()
    assert not kit.exists(),'Keep existing extracted drivers; choose a clean preparation directory'
    kit.mkdir(parents=True)
    def extract(source,target):
        subprocess.run([str(args.seven_zip),'x',str(source),'-o'+str(target),'-y'],check=True,capture_output=True,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    extract(args.cache/spec['parts'][0]['file'],kit/'package')
    bundle=kit/'package/BlackBerry-USBDrivers-5.0.0.2.exe'
    assert sha(bundle)==spec['bundle_sha256']
    def signature(path):
        powershell=shutil.which('pwsh.exe') or shutil.which('powershell.exe')
        assert powershell,'A Windows PowerShell host is required for Authenticode validation'
        return json.loads(subprocess.check_output([powershell,'-NoProfile','-File',
            str(ROOT/'tools/verify_signature.ps1'),'-Path',str(path)],text=True))
    signed=signature(bundle)
    extract(bundle,kit/'bootstrapper')
    tree=ET.parse(kit/'bootstrapper/0')
    ns={'b':'http://schemas.microsoft.com/wix/2008/Burn'}
    container=tree.find('b:Container',ns).attrib
    data=bundle.read_bytes();start=0;found=False
    while True:
        start=data.find(b'MSCF\x00\x00\x00\x00',start)
        if start<0:break
        size=struct.unpack_from('<I',data,start+8)[0]
        block=data[start:start+size]
        if size==int(container['FileSize']) and hashlib.sha1(block).hexdigest().upper()==container['Hash']:
            (kit/'payload.cab').write_bytes(block);found=True;break
        start+=8
    assert found,'Embedded CAB does not match the signed bundle manifest'
    extract(kit/'payload.cab',kit/'payload')
    item=next(x.attrib for x in tree.findall('b:Payload',ns) if x.attrib['Id']=='Msi64b')
    raw=kit/'payload'/item['SourcePath']
    assert hashlib.sha1(raw.read_bytes()).hexdigest().upper()==item['Hash']
    msi=kit/'USBInstallerMSIx64.msi';shutil.copyfile(raw,msi)
    assert sha(msi)==spec['msi_sha256']
    extract(msi,kit/'extracted')
    drivers=kit/'rim-usb';drivers.mkdir()
    for name,digest in spec['driver_files'].items():
        candidates=list((kit/'extracted').rglob(name))+list((kit/'extracted').rglob(name+'.*'))
        matches=[p for p in candidates if p.is_file() and sha(p)==digest]
        assert len(matches)==1,'Cannot uniquely identify verified driver: '+name
        shutil.copyfile(matches[0],drivers/name)
    catalog=signature(drivers/'rimusbnt.cat')
    report={'prepared':True,'windows_installation_performed':False,
            'bundle_signature':signed,'driver_catalog_signature':catalog,'x64_msi_matches_signed_manifest':True}
    (kit/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
