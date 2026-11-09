"""Build the prepared owner-specific Root images offline and verify original partitions."""
import argparse
import json
import subprocess
from pathlib import Path
from fetch_materials import sha
from desktop_paths import resource_root, private_root
from root_images import recipe, verify_build

ROOT=resource_root()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kit',type=Path,default=private_root()/'root-kit')
    args=p.parse_args(argv)
    kit=args.kit.resolve()
    preparation=json.loads((kit/'preparation.json').read_text())
    assert preparation['offline_preparation_complete']
    variant=preparation['variant']
    stock,_=recipe(variant)
    assert preparation['firmware_id']==stock['id'] and preparation['stock_sha256']==stock['extracted_sha256']
    original=kit/'stock'/stock['extracted_file']
    assert sha(original)==stock['extracted_sha256']
    output=kit/'images'
    assert output.is_dir() and not any(output.iterdir()),'Use an empty output folder; preserve existing images'
    with (kit/'root-build.log').open('wb') as log:
        from preparation_cache import run_preparation
        result=run_preparation([str(kit/'autoroot/bb10mt.exe'),'batch','-i',str(original),
            '-s','patch-owner.txt','-o',str(output)],kit,cwd=kit/'autoroot',stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,'Image builder failed; inspect the private root-build.log'
    report=verify_build(kit,variant)
    print(json.dumps(report))


if __name__=='__main__':main()
