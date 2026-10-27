"""Build the prepared owner-specific Root images offline and verify original partitions."""
import argparse
import json
import subprocess
from pathlib import Path
from fetch_materials import sha

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kit',type=Path,default=ROOT/'private/root-kit')
    args=p.parse_args()
    kit=args.kit.resolve()
    preparation=json.loads((kit/'preparation.json').read_text())
    assert preparation['offline_preparation_complete']
    source=json.loads((ROOT/'materials/sources.json').read_text())
    stock=next(x for x in source['verified_inputs'] if x['id']=='stock-q10')
    original=kit/'stock'/stock['extracted_file']
    assert sha(original)==stock['extracted_sha256']
    output=kit/'images'
    assert output.is_dir() and not any(output.iterdir()),'Use an empty output folder; preserve existing images'
    with (kit/'root-build.log').open('wb') as log:
        result=subprocess.run([str(kit/'autoroot/bb10mt.exe'),'batch','-i',str(original),
            '-s','patch-owner.txt','-o',str(output)],cwd=kit/'autoroot',stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,'Image builder failed; inspect the private root-build.log'
    expected=json.loads((ROOT/'materials/stock-partitions.json').read_text())
    verified=[]
    for item in expected['unchanged_partitions']:
        path=output/item['file']
        assert path.stat().st_size==item['bytes'] and sha(path)==item['sha256'],'Unexpected original-partition change: '+item['file']
        verified.append(item['file'])
    radios=list(output.glob('*.1.signed'))
    assert len(radios)==1 and sha(radios[0])==expected['radio_original_sha256']
    images=[]
    for suffix in ('_os.exe','_radio.exe'):
        files=list(output.glob('*'+suffix));assert len(files)==1
        images.append({'file':files[0].name,'bytes':files[0].stat().st_size,'sha256':sha(files[0])})
    report={'offline_build_verified':True,'phone_connected_or_modified':False,
            'unchanged_partitions':verified,'radio_original_sha256':expected['radio_original_sha256'],
            'images':images,'keys':'Private and unique to this prepared kit; image hashes vary with keys'}
    (kit/'build-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
