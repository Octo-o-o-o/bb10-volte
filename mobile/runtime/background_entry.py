"""Execute a recorded job in its own QNX application group. Python 3.2."""
import sys
sys.path[:] = ['/usr/lib/python32.zip', '/usr/lib/python3.2', '/usr/lib/python3.2/lib-dynload']
import os
import re

if __name__ == '__main__':
    if os.geteuid() != 0 or os.uname()[0] != 'QNX' or len(sys.argv) != 3:
        sys.exit(1)
    folder = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if not re.match(r'\A/var/bb10_volte-mobile/snapshots/[a-f0-9]{64}\Z', folder):
        sys.exit(1)
    sys.path.insert(0, folder + '/runtime')
    import entry as e
    bundle = e.read_bundle(folder)
    e.require(e.digest(bundle[1]) == os.path.basename(folder), 'background_bundle_changed')
    sys.path.insert(0, folder + '/payload/device')
    sys.path.insert(0, folder + '/runtime')
    import worker
    job_id, attempt = worker.checked_id(sys.argv[1]), worker.checked_id(sys.argv[2])
    job = worker.load(worker.job_path(job_id))
    e.require(job['bundle'] == folder, 'background_bundle_changed')
    fallback = job.get('fallback_manifest_sha', os.path.basename(folder))
    e.require(isinstance(fallback, str) and re.match(r'\A[a-f0-9]{64}\Z', fallback), 'background_bundle_changed')
    e.FALLBACK_MANIFEST_SHA = fallback
    os.umask(0o077)
    worker.run_job(job_id, attempt)
