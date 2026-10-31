"""Desktop bridge for the hash-pinned, accepted Q20 installation already present."""
import hashlib
import json
import re
import shlex
import time
import uuid

from desktop_paths import private_root, resource_root

BASE = '/var/q20_volte'
GUARD = 'case "$(cat /pps/services/deviceproperties)" in *"modelnumber::SQC100-2"*) ;; *) exit 93;; esac; '


def bundle():
    root = resource_root()
    spec = json.loads((root / 'materials/q20-managed-adapter.json').read_text(encoding='utf-8'))
    source = root / 'tools/q20_manage_probe.py'
    if (spec['schema'] != 1 or spec['variant'] != 'SQC100-2' or spec['base'] != BASE or
            hashlib.sha256(source.read_bytes()).hexdigest() != spec['probe_sha256']):
        raise ValueError('Q20 management package changed')
    return spec, source


class Adapter:
    def __init__(self, client):
        self.client = client

    def invoke(self, action):
        from workflow import ENV, WorkflowError
        try:
            spec, source = bundle()
        except (OSError, ValueError, KeyError, TypeError):
            raise WorkflowError('package_mismatch') from None
        stage = '/var/q20_app_probe_' + uuid.uuid4().hex[:12]
        c = self.client
        raw = c.remote(GUARD + 'cat ' + BASE + '/payload-manifest.json').encode('ascii')
        expected = hashlib.sha256(raw).hexdigest()
        accepted = {spec['manifest_sha256']} | set(spec.get('additional_manifest_sha256', []))
        if expected not in accepted:
            raise WorkflowError('package_mismatch')
        c.remote(GUARD + 'test ! -e ' + stage + ' && mkdir -m 700 ' + stage)
        c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options +
                  [str(source), c.host + ':' + stage + '/probe.py'], 40)
        output = c.remote(GUARD + '/proc/boot/pathtrust !' + stage + '/probe.py && ' + ENV +
                          '/usr/bin/python3.2 ' + stage + '/probe.py ' + shlex.quote(action) +
                          ' ' + expected, 180)
        try:
            return json.loads(output)
        except ValueError:
            raise WorkflowError('invalid_device_response') from None

    def inspect(self):
        from workflow import public_status
        report = self.invoke('inspect')
        report['status'] = public_status(report['status'])
        return report

    def service(self, action):
        if action == 'status':
            return self.inspect()['status']
        if action == 'start':
            return self.action('start')
        if action == 'stop':
            return self.action('disable')
        from workflow import WorkflowError
        raise WorkflowError('invalid_action')

    def backup(self, plan):
        from workflow import profiles, WorkflowError
        try:
            folder = plan['folder']
            if not re.fullmatch(re.escape(BASE) + r'/state/dca-usage-[0-9]{8}T[0-9]{6}Z', folder):
                raise ValueError('Q20 backup path')
            c = self.client
            dest = private_root() / ('q20-telecom-backup-' + uuid.uuid4().hex)
            dest.mkdir(parents=True)
            for name in ('plan.json', 'ims.original', 'ims_defaults.original', 'omadm.original', 'test.original'):
                c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options +
                          [c.host + ':' + folder + '/' + name, str(dest / name)], 40)
            raw = (dest / 'plan.json').read_bytes()
            value = json.loads(raw)
            digest = hashlib.sha256(raw).hexdigest()
            if value['owner'] != 'q20-dca-usage-trial-v1' or digest != plan['plan_sha256']:
                raise ValueError('Q20 plan owner/hash')
            if set(value['files']) != {'ims', 'ims_defaults', 'omadm', 'test'}:
                raise ValueError('Q20 original set')
            for name, item in value['files'].items():
                if hashlib.sha256((dest / (name + '.original')).read_bytes()).hexdigest() != item['original_sha256']:
                    raise ValueError('Q20 original backup')
            receipt = {'owner': value['owner'], 'plan_sha256': digest, 'all_original_hashes_verified': True}
            local = dest / 'desktop-backup-receipt.json'
            local.write_bytes(profiles.canonical(receipt))
            c.process([c.scp, '-S', c.ssh, '-O', '-q'] + c.options +
                      [str(local), c.host + ':' + folder + '/desktop-backup-receipt.json'], 40)
        except (OSError, ValueError, KeyError, TypeError):
            raise WorkflowError('telecom_backup_not_verified') from None

    def action(self, action):
        from workflow import WorkflowError, registered
        if action == 'status':
            report = self.inspect()
            return {'preflight': report, 'status': report['status'], 'registered': registered(report['status'])}
        if action == 'start':
            report = self.inspect()
            if report['status']['manager_alive']:
                return {'preflight': report, 'status': report['status'], 'already_started': True,
                        'registration': 'verified' if registered(report['status']) else 'pending'}
            if not report['can_start']:
                raise WorkflowError('preflight_blocked', report)
            plan = self.invoke('prepare')
            if report['profile_parameters']['carrier']['mncs'] == ['11']:
                self.backup(plan)
            elif not (plan.get('prepared') is True and plan.get('backup_required') is False and
                      plan.get('profile_sha256') == report['profile_sha256']):
                raise WorkflowError('preflight_blocked', report)
            self.invoke('start')
            return self.client.wait_registration(timeout=report['profile_parameters']['runtime']['registration_wait_seconds'])
        if action in ('stop', 'disable'):
            self.invoke('disable')
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                report = self.inspect()
                if not report['status']['manager_alive']:
                    phase = report['status']['phase']
                    restored = phase in ('stopped', 'configuration_restored_reboot_required') or report['can_start']
                    if not restored:
                        raise WorkflowError('restore_needs_inspection', report)
                    return {'restored': True, 'reboot_required': phase == 'configuration_restored_reboot_required',
                            'preflight': report, 'status': report['status']}
                time.sleep(3)
            raise WorkflowError('restore_pending')
        raise WorkflowError('q20_managed_existing_only')
