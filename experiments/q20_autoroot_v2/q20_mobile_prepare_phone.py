"""Inspect or hand off one exact idle stock IMS instance before Mobile setup."""
import json
import re
import sys
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    assert q.s.ACTIVE_PROFILE['id'] == 'q20-sqc100-2-mobile-46000'
    assert q.s.phone_idle() and not q.n.active_vpn_sessions()
    assert q.n.crypto_policy() == {'swcr_id': -1, 'crypto_support': 0}
    assert q.n.voice_policy() == 0 and all(q.c.configuration_diagnostics().values())
    imsi = q.s.current_usim()
    pids = q.n.ims_pids()
    result = {'pids': pids, 'stock_handoff_requested': False, 'configuration_writes': 0,
              'telecom_usage_policy_applied': False, 'network': q.c.read_network(q.s.ACTIVE_PROFILE)}
    if pids:
        assert len(pids) == 1
        pid = pids[0]
        arguments = q.n.command(['/bin/pidin', '-p', str(pid), '-f', 'A']).decode('ascii')
        data = q.n.command(['/bin/slog2info', '-b', 'ims_rrm'], 10).decode('utf-8', 'replace')
        own = '\n'.join(line for line in data.splitlines() if 'ims_rrm.' + str(pid) + ' ' in line)
        result.update(exact_stock_arguments=arguments.strip().splitlines()[-1].strip() ==
                      '/radio/bin/ims_rrm -U 453:31,80,387,427,521,1001',
                      no_profiles_wait='No IMS profiles provisioned .. waiting' in own,
                      register_or_invite_observed=bool(re.search(r'CSeq:\s*\d+\s+(?:REGISTER|INVITE)\b', own)),
                      live=q.live())
    action = sys.argv[1]
    assert action in ('inspect', 'handoff')
    if action == 'handoff':
        if pids:
            assert result['exact_stock_arguments'] and result['no_profiles_wait']
            assert not result['register_or_invite_observed'] and q.s.current_usim() == imsi
            # This hash-pinned helper only validates and hands off a stock
            # no-profile process. It does not invoke the Telecom bootstrap.
            import q20_telecom_carrier as carrier
            carrier.wait_for_idle_stock(q)
            result['stock_handoff_requested'] = True
        assert not q.n.ims_pids() and q.s.current_usim() == imsi
        result['precheck'] = q.precheck()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
