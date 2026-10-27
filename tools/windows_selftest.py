"""Offline packaged-runtime smoke test; never contacts or changes a phone."""
import json
import shutil
import subprocess
import sys
import tkinter as tk

from desktop_paths import frozen, private_root, resource_root
from workflow import Client, verify_package, CREATE_NO_WINDOW
from profile_editor import presets, ProfileEditor


def run(output):
    def no_python_network(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo', 'socket.bind'):
            raise RuntimeError('Packaging self-test must not use the network')
    sys.addaudithook(no_python_network)
    from gui import App
    bundle = resource_root()
    manifest = verify_package()
    root = tk.Tk()
    root.withdraw()
    app = App(root)
    editor = ProfileEditor(root, app.profile, app.set_profile)
    editor.withdraw()
    assert editor.value() == app.profile
    editor.destroy()
    root.update_idletasks()
    tcl, tk_version = root.tk.call('info', 'patchlevel'), root.tk.call('package', 'provide', 'Tk')
    root.destroy()
    client = Client()
    ssh = subprocess.run([client.ssh, '-V'], capture_output=True, text=True, timeout=15,
                         creationflags=CREATE_NO_WINDOW)
    scp = subprocess.run([client.scp], capture_output=True, text=True, timeout=15,
                         creationflags=CREATE_NO_WINDOW)
    assert ssh.returncode == 0 and 'OpenSSH' in ssh.stderr
    assert scp.returncode == 1 and 'usage:' in scp.stderr
    assert (bundle / 'docs/GUI.md').is_file()
    assert (bundle / 'tools/stage_cleanup.py').is_file()
    transferred = []
    def local_transfer(args, timeout):
        source = resource_root() / args[-2]
        assert source.is_file()
        transferred.append(source)
        return ''
    # Exercise the frozen staging paths without invoking a transport operation.
    client.remote = lambda *args: ''
    client.process = local_transfer
    client.execute = lambda *args: {'stage_removed': True}
    with client.stage():
        pass
    assert bundle / 'tools/stage_cleanup.py' in transferred
    assert len(transferred) == 6
    if frozen():
        assert (bundle / 'licenses/THIRD-PARTY-NOTICES.txt').stat().st_size > 1000
        assert (bundle / 'assets/app.ico').is_file()
        assert not private_root().is_relative_to(bundle)
    result = {'passed': True, 'version': manifest['version'], 'frozen': frozen(),
              'python': sys.version.split()[0], 'tcl': tcl, 'tk': tk_version,
              'python_on_path': bool(shutil.which('python')),
              'system_ssh_on_path': bool(shutil.which('ssh')),
              'bundled_ssh': client.ssh.startswith(str(bundle / 'vendor/openssh')),
              'ssh_version': ssh.stderr.strip(), 'scp_available': True,
              'payload_files_verified': len(manifest['files']),
              'qnx_stage_cleanup_resource_present': True,
              'offline_staging_inputs_verified': len(transferred),
              'profiles_loaded': len(presets()), 'editor_roundtrip': True,
              'persistent_state_outside_bundle': not private_root().is_relative_to(bundle),
              'python_network_disabled_during_selftest': True,
              'phone_contacted': False}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0
