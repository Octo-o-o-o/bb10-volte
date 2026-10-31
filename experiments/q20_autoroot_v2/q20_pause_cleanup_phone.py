"""Finish only the owned voice-preference rollback when the owner pauses."""
import json
import os
import re
import time
import q20_volte_phone as q


def main():
    q.setup()
    q.verify()
    assert q.s.phone_idle()
    runs = sorted(name for name in os.listdir(q.s.STATE) if re.match(r'^voice-trial-[0-9]{8}T[0-9]{6}Z$', name))
    assert runs
    folder = q.s.STATE + '/' + runs[-1]
    previous = q.s.load(folder + '/report.json')
    assert previous['original_voice_policy'] == 0 and previous['voice_policy_change_attempted']
    try:
        before = q.n.voice_policy()
    except Exception:
        before = None
    assert before in (None, 0, 3)
    result = {'owner_requested_wait': True, 'before_policy': before, 'original_policy': 0,
              'new_experiments_started': False}
    if before != 0:
        result['restore_request'] = q.s.set_voice_preference(4)
        assert result['restore_request']['rc'] == 0
    after = None
    for unused in range(5):
        try:
            after = q.n.voice_policy()
            if after == 0:
                break
        except Exception:
            pass
        time.sleep(2)
    result.update(after_policy=after, restored=after == 0, boot=q.boot_token())
    q.n.atomic(folder + '/pause-restore.json', json.dumps(result).encode('ascii'))
    if after == 0:
        q.n.atomic(folder + '/done', b'owner pause: original voice policy00 verified\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
