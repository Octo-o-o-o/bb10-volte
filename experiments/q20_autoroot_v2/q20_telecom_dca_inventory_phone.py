"""Read-only source-level DCA inventory for the verified Q20."""
import json
import os
import stat
import q20_volte_phone as q
from q20_telecom_native_probe_phone import QCT_HASH, ue_usage_policy


def main():
    q.setup()
    q.verify()
    assert q.n.digest(q.n.read('/radio/bin/qct_rrm')) == QCT_HASH
    result = {'variant': 'SQC100-2', 'configuration_writes': 0, 'files': {},
              'ue_usage_setting': ue_usage_policy(), 'voice_policy': q.n.voice_policy()}
    for name in ('ims', 'ims_defaults', 'omadm', 'test'):
        path = '/var/dca/sources/' + name + '/services/carrier_config/radio_common/cellular_protocol_configuration'
        item = {'exists': os.path.lexists(path), 'symlink': os.path.islink(path)}
        if os.path.isfile(path):
            blob = q.n.read(path)
            attrs = q.n.attrs(blob)
            info = os.lstat(path)
            item.update(sha256=q.n.digest(blob), bytes=len(blob), mode=info.st_mode & 0o7777,
                        uid=info.st_uid, gid=info.st_gid, regular=stat.S_ISREG(info.st_mode),
                        attribute_names=sorted(attrs),
                        ue_usage_setting=q.n.value(attrs, 'ue_usage_setting'),
                        voice_domain=q.n.value(attrs, 'voice_domain_preference_EUTRAN'))
        result['files'][path] = item
    for family in ('radio_common', 'radio_qct'):
        path = '/pps/services/carrier_config/' + family + '/cellular_protocol_configuration'
        attrs = q.n.attrs(q.n.read(path)) if os.path.isfile(path) else {}
        result[family] = {'attribute_names': sorted(attrs),
                         'ue_usage_setting': q.n.value(attrs, 'ue_usage_setting'),
                         'voice_domain': q.n.value(attrs, 'voice_domain_preference_EUTRAN')}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
