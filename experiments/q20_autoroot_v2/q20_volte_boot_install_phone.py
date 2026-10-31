"""Add the verified Q20-only background hook after manual call acceptance."""
import json
import os
import stat
import sys
import q20_volte_phone as q

BTOOL = '/apps/sys.android.gYABgKAOw1czN6neiAT72SGO.ns/native/system/xbin/btool'
HOOK = (b'\n# codex-q20-volte-boot-v1\n'
        b'if [ -f /var/q20_volte/enabled ]; then\n'
        b'    ( /proc/boot/pathtrust !/var/q20_volte/start.sh && /bin/sh /var/q20_volte/start.sh )'
        b' >> /var/q20_volte/state/boot-launch.log 2>&1 &\nfi\n')


def patched_root_script(original):
    anchor = b'. /base/scripts/sudtools.sh\n'
    assert original.count(anchor) == 1
    assert b'codex-q20-volte-boot-v1' not in original
    return original.replace(anchor, HOOK + anchor, 1)


def main():
    q.setup()
    q.verify()
    relocating = len(sys.argv) == 2 and sys.argv[1] == 'relocate'
    assert q.s.phone_idle()
    if not relocating:
        assert q.status()['registered'] is True
    receipt = q.s.load(q.BASE + '/state/manual-call-acceptance.json')
    assert receipt['owner'] == 'q20-call-acceptance-v1' and receipt['variant'] == 'SQC100-2'
    assert receipt['profile_sha256'] == q.profiles.fingerprint(q.s.ACTIVE_REQUEST)
    assert all(receipt[key] is True for key in
               ('incoming', 'outgoing', 'audio_both_directions', 'lte', 'sip_dialogs_verified'))
    plan = q.s.load(q.BASE + '/state/boot-plan.json')
    current = q.n.read(BTOOL)
    if relocating:
        previous = q.s.load(q.BASE + '/state/boot-install.json')
        assert previous['owner'] == 'q20-boot-hook-v1' and previous['phase'] == 'enabled'
        assert q.n.digest(current) == previous['after_sha256']
        assert current.count(HOOK) == 1
        original = current.replace(HOOK, b'', 1)
    else:
        original = current
    assert q.n.digest(original) == plan['btool_before_sha256'], 'Root script changed; preserve it'
    assert b'codex-q20-volte-boot-v1' not in original
    # The original v2 script has no trailing newline; HOOK starts with one.
    assert HOOK.startswith(b'\n') and not os.path.islink(BTOOL)
    after = patched_root_script(original)
    assert q.n.digest(after) == plan['btool_after_sha256']
    assert q.n.digest(q.n.read(q.BASE + '/start.sh')) == plan['start_sha256']
    q.n.command(['/proc/boot/pathtrust', '!' + q.BASE + '/start.sh'])
    q.n.command(['/bin/sh', '-n', q.BASE + '/start.sh'])
    if not relocating:
        q.n.atomic(q.BASE + '/state/btool-original.sh', original)
    else:
        assert q.n.read(q.BASE + '/state/btool-original.sh') == original
    st = os.stat(BTOOL)
    transaction = {'owner': 'q20-boot-hook-v1', 'before_sha256': q.n.digest(original),
                   'after_sha256': q.n.digest(after), 'phase': 'write_pending',
                   'inode_before': st.st_ino, 'mode_before': stat.S_IMODE(st.st_mode)}
    if os.path.exists(q.BASE + '/enabled'):
        os.unlink(q.BASE + '/enabled')
    q.n.atomic(q.BASE + '/state/boot-install.json', json.dumps(transaction).encode('ascii'))
    # Preserve the inode, owner, ACL and PathTrust attributes. Insert before
    # the legacy installer's unbounded Term49 wait; all original bytes remain
    # in their original order. The added entry itself is asynchronous.
    with open(BTOOL, 'r+b') as output:
        assert output.write(after) == len(after)
        output.truncate(len(after))
        output.flush()
        os.fsync(output.fileno())
    assert q.n.read(BTOOL) == after
    assert os.stat(BTOOL).st_ino == st.st_ino
    assert stat.S_IMODE(os.stat(BTOOL).st_mode) == stat.S_IMODE(st.st_mode)
    q.n.atomic(q.BASE + '/enabled', b'enabled after owner-confirmed Q20 bidirectional LTE calls\n')
    transaction.update(phase='enabled', original_root_bytes_preserved=True,
                       hook_runs_in_background=True, enabled=True,
                       placement='before_legacy_term49_install_wait')
    q.n.atomic(q.BASE + '/state/boot-install.json', json.dumps(transaction).encode('ascii'))
    print(json.dumps(transaction))


if __name__ == '__main__':
    main()
