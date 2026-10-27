"""Run one build/notary command in the logged-in macOS user's GUI session."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-root', type=Path, required=True)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--environment', type=Path, help='build-environment.json from runtime preparation')
    parser.add_argument('--clean-python-env', action='store_true', help='Remove Python/Tcl/DYLD overrides')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    assert sys.platform == 'darwin' and args.timeout > 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    assert command and Path(command[0]).is_absolute(), 'Use an absolute executable path'
    jobs = args.job_root.expanduser().resolve()/'jobs'
    jobs.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    job = jobs/token
    job.mkdir()
    label = 'org.bb10volte.job.'+token
    payload = {'command': command, 'cwd': str(args.cwd.expanduser().resolve()),
               'status': str(job/'status.json'), 'log': str(job/'output.log'),
               'clean': args.clean_python_env}
    if args.environment:
        env = json.loads(args.environment.read_text(encoding='utf-8'))
        payload['framework_path'] = env['DYLD_FRAMEWORK_PATH']
    (job/'payload.json').write_text(json.dumps(payload), encoding='utf-8')
    wrapper = job/'run.py'
    wrapper.write_text("""import json,os,pathlib,subprocess,sys,traceback\np=json.loads(pathlib.Path(sys.argv[1]).read_text())\ne=os.environ.copy()\ne['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'\nif p['clean']:\n for k in ('PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY','DYLD_FRAMEWORK_PATH','DYLD_LIBRARY_PATH','VIRTUAL_ENV'): e.pop(k,None)\nif 'framework_path' in p:e['DYLD_FRAMEWORK_PATH']=p['framework_path']\ntry:\n with open(p['log'],'w',encoding='utf-8') as out:\n  r=subprocess.run(p['command'],cwd=p['cwd'],env=e,stdout=out,stderr=subprocess.STDOUT)\n result={'returncode':r.returncode}\nexcept Exception:\n with open(p['log'],'a',encoding='utf-8') as out:traceback.print_exc(file=out)\n result={'returncode':1}\ntmp=pathlib.Path(p['status']+'.partial');tmp.write_text(json.dumps(result));tmp.replace(p['status'])\n""", encoding='utf-8')
    plist = job/'job.plist'
    with plist.open('wb') as f:
        plistlib.dump({'Label': label, 'ProgramArguments': [sys.executable, str(wrapper), str(job/'payload.json')],
                       'RunAtLoad': True, 'StandardOutPath': str(job/'launcher.out'),
                       'StandardErrorPath': str(job/'launcher.err')}, f)
    domain = 'gui/'+str(os.getuid())
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(plist)], check=True)
    print(json.dumps({'job': str(job), 'label': label}), flush=True)
    deadline = time.monotonic()+args.timeout
    while time.monotonic() < deadline:
        if (job/'status.json').is_file():
            status = json.loads((job/'status.json').read_text())
            subprocess.run(['/bin/launchctl', 'bootout', domain+'/'+label], capture_output=True)
            print(json.dumps(status), flush=True)
            return status['returncode']
        time.sleep(1)
    # The operation might still be running. Preserve its job and inspect the
    # status/output before retrying a signing or notarization submission.
    print(json.dumps({'timeout': True, 'job_still_registered': True}), flush=True)
    return 124


if __name__ == '__main__':
    sys.exit(main())
