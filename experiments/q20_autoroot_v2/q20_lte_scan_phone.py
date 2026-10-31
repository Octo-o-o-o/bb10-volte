"""One LTE network scan on the verified, idle Q20; no selection setters."""
import json
import os
import time
import q20_volte_phone as q
from q20_nas_client_phone import NasClient


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle() and not q.n.active_vpn_sessions()
    assert not os.path.exists(q.BASE + '/enabled')
    assert q.n.voice_policy() == 0 and q.n.crypto_policy()['swcr_id'] == -1
    result = {'variant': 'SQC100-2', 'started_unix': time.time(),
              'configuration_writes': 0, 'network_selection_setters': 0}
    with NasClient() as client:
        before = client.request(0x34)
        assert before['mode_preference_mask'] == 28 and before['usage_preference'] == 1
        result['before'] = before
        try:
            result['scan'] = client.request(0x21, b'\x10\x01\x00\x04')
        except Exception as error:
            result['scan_error_type'] = type(error).__name__
        result['after'] = client.request(0x34)
        result['serving'] = client.request(0x24)
        result['system'] = client.request(0x4d)
    result['ended_unix'] = time.time()
    filename = q.s.STATE + '/lte-scan-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '.json'
    q.n.atomic(filename, json.dumps(result, indent=2).encode('ascii'))
    result['private_report'] = filename
    print(json.dumps(result))


if __name__ == '__main__':
    main()
