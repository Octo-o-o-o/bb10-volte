"""Rebuild the exact freestanding QNX-loaded ARM helper with Zig0.13.0."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='504a6f5bdfb55f03aaf64b1a73f423e1a802e4786433f2621cd701c993224254'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zig',required=True);args=p.parse_args()
    assert subprocess.check_output([args.zig,'version'],text=True).strip()=='0.13.0'
    build=ROOT/'build';build.mkdir(exist_ok=True)
    obj=build/'devnp-volte_swcrypto_probe.o';out=build/'devnp-volte_swcrypto_probe.so'
    subprocess.run([args.zig,'cc','-target','arm-linux-gnueabi','-mcpu=cortex_a9','-mthumb',
        '-ffreestanding','-fno-builtin','-fno-stack-protector','-fno-sanitize=all','-fno-unwind-tables',
        '-fno-asynchronous-unwind-tables','-fPIC','-O2','-g0','-ffunction-sections','-fdata-sections',
        '-fvisibility=hidden','-c',str(ROOT/'driver/volte_swcrypto.c'),'-o',str(obj)],check=True)
    subprocess.run([args.zig,'ld.lld','-shared','-m','armelf_linux_eabi','--gc-sections','--hash-style=sysv',
        '--no-rosegment','-z','norelro','-z','max-page-size=4096','-z','separate-loadable-segments',
        '--version-script='+str(ROOT/'driver/helper.exports'),'-soname',out.name,'-s',str(obj),'-o',str(out)],check=True)
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    assert digest==EXPECTED,'Different build output; do not deploy without native ABI validation: '+digest
    print(json.dumps({'reproduced':True,'bytes':out.stat().st_size,'sha256':digest}))

if __name__=='__main__':main()
