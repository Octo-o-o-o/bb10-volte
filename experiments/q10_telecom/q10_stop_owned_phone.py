"""Stop only the verified existing Q10 baseline, immediately after idle proof."""
import ctypes
import os
import native as n
import compatibility as c
import device_info


def main():
    identity = device_info.read_identity()
    assert identity['variant'] == 'SQN100-3' and identity['os_version'] == '10.3.3.3216'
    assert os.geteuid() == 0 and os.uname()[0] == 'QNX' and ctypes.sizeof(ctypes.c_void_p) == 4
    n.verify_stock()
    installed = c.installed_state()
    assert installed['payload_verified'] is True and installed['version'] == '0.3.2'
    assert installed['carrier_profile_id'] == 'unicom-46001-baseline'
    assert installed['carrier_profile_sha256'] == '0692b9e16b75ef6fc027d1aefa6c521640ba84840b96d6cb01ad6ba96477d756'
    for path in ('/pps/services/phone/public/calls', '/pps/services/phone/private/calls'):
        assert os.path.isdir(path) and not os.listdir(path), 'Call active: preserve service'
    base = '/var/rootdata/q10_volte'
    for name in ('native.py', 'profiles.py', 'device_info.py', 'compatibility.py', 'install.py'):
        path = base + '/device/' + name
        assert os.path.isfile(path) and not os.path.islink(path)
        n.command(['/proc/boot/pathtrust', '!' + path])
    os.execv('/usr/bin/python3.2', ['/usr/bin/python3.2', base + '/device/install.py', 'disable'])


if __name__ == '__main__':
    main()
