"""Connection migration, pinned trust and bounded automatic discovery."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import connection as c
import workflow as w


class ConnectionTests(unittest.TestCase):
    def test_first_use_kits_are_discovered_after_restart_and_verified_before_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            private = base / 'private'
            configs = []
            for name in ('root-kit', 'root-kit-123abc', 'backup/root-kit-hidden', 'other'):
                path = private / name / 'ssh_config'
                path.parent.mkdir(parents=True)
                path.write_text('Host bb10-root q10-root\n HostName 169.254.0.1\n User root\n')
                configs.append(path)
            old, current = configs[:2]
            clients = []
            def make_client(host, config, **options):
                client = MagicMock()
                client.process.return_value = 'hostname 169.254.0.1\nuser root\n'
                if Path(config) == old:
                    client.remote.side_effect = w.WorkflowError('host_key_mismatch')
                else:
                    client.remote.return_value = 'BB10_CONNECTION_READY\n'
                clients.append((Path(config), client))
                return client
            with patch.object(c, 'private_root', return_value=private), \
                    patch.object(c, 'frozen', return_value=True), \
                    patch.object(c.Path, 'home', return_value=base / 'home'), \
                    patch.object(c.sys, 'executable', str(base / 'app/app.exe')), \
                    patch.object(c, 'Client', side_effect=make_client):
                choices = c.candidate_connections()
                self.assertEqual({Path(item['config']) for item in choices}, {old, current})
                self.assertTrue(all(not item['saved'] for item in choices))
                _, selected = c.resolve_connection('bb10-root', '')
                self.assertEqual(Path(selected['config']), current)
                self.assertIsNone(c.saved_connection())
            self.assertTrue(all(client.process.called and client.remote.called for _, client in clients))

    def test_portable_exe_finds_numbered_kits_in_its_source_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            (base / 'project.json').write_text(json.dumps({'name': 'bb10-volte'}))
            config = base / 'private/root-kit-123abc/ssh_config'
            config.parent.mkdir(parents=True)
            config.write_text('Host q10-root\n')
            with patch.object(c, 'private_root', return_value=base / 'user-private'), \
                    patch.object(c, 'frozen', return_value=True), \
                    patch.object(c.Path, 'home', return_value=base / 'home'), \
                    patch.object(c.sys, 'executable', str(base / 'dist/app.exe')):
                self.assertEqual(c.candidate_connections(),
                                 [{'host': 'q10-root', 'config': str(config), 'saved': False}])

    def test_legacy_alias_is_selected_from_an_explicit_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ssh_config'
            path.write_text('Host q10-root\n HostName 169.254.0.1\n User root\n')
            self.assertEqual(c.matching_alias(path, 'bb10-root'), 'q10-root')
            self.assertEqual(c.matching_alias(path, 'my-phone'), 'my-phone')
            with patch.object(c, 'Client') as client:
                _, choice = c.resolve_connection('bb10-root', str(path))
                self.assertEqual(choice['host'], 'q10-root')
                client.assert_called_once_with('q10-root', str(path))

    def test_wildcard_host_is_not_an_automatic_phone_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config'
            path.write_text('Host *\n User root\nHost bb10-*\n HostName other-host\n')
            self.assertEqual(c.aliases(path), [])

    def test_saved_connection_contains_references_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(c, 'private_root', return_value=Path(folder)):
            path = Path(folder) / 'ssh_config'
            path.write_text('Host q10-root\n')
            c.save_connection('q10-root', str(path))
            self.assertEqual(c.saved_connection(), {'host': 'q10-root', 'config': str(path)})
            self.assertEqual(set(json.loads((Path(folder) / 'connection.json').read_text())), {'host', 'config'})

    def test_unsaved_remote_host_or_proxy_is_never_contacted_automatically(self):
        choice = {'host': 'q10-root', 'config': 'test.conf', 'saved': False}
        for effective in ('hostname other-host\nuser root\n',
                          'hostname 169.254.0.1\nuser root\nproxyjump other-host\n'):
            client = MagicMock()
            client.process.return_value = effective
            with patch.object(c, 'candidate_connections', return_value=[choice]), patch.object(c, 'Client', return_value=client):
                with self.assertRaisesRegex(w.WorkflowError, 'connection_setup_required'):
                    c.resolve_connection('bb10-root', '')
            client.remote.assert_not_called()

    def test_local_verified_profile_can_be_used_without_a_filled_gui_field(self):
        client = MagicMock()
        client.process.return_value = 'hostname 169.254.0.1\nuser root\n'
        client.remote.return_value = 'BB10_CONNECTION_READY\n'
        choice = {'host': 'q10-root', 'config': 'test.conf', 'saved': False}
        with patch.object(c, 'candidate_connections', return_value=[choice]), patch.object(c, 'Client', return_value=client):
            result, used = c.resolve_connection('bb10-root', '')
        self.assertIs(result, client)
        self.assertEqual(used['host'], 'q10-root')

    def test_dns_and_ssh_failures_are_classified_without_claiming_missing_root(self):
        messages = [('Could not resolve hostname bb10-root', 'hostname_unresolved'),
                    ('no matching MAC found', 'ssh_algorithm_mismatch'),
                    ('Connection refused', 'connection_refused'),
                    ('Permission denied (publickey)', 'authentication_failed')]
        with patch.object(w.shutil, 'which', side_effect=lambda name: name):
            client = w.Client()
        for message, code in messages:
            result = MagicMock(returncode=255, stderr=message)
            with patch.object(w.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(w.WorkflowError, code):
                    client.process(['ssh'], 1)
        self.assertIn('MACs=hmac-sha1', client.options)
        self.assertIn('StrictHostKeyChecking=yes', client.options)

    def test_known_python_security_rejection_is_not_reported_as_network_failure(self):
        with patch.object(w.shutil, 'which', side_effect=lambda name: name):
            client = w.Client()
        result = MagicMock(returncode=255, stderr='/usr/bin/python3.2: -c option disabled for euid 0\n')
        with patch.object(w.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(w.WorkflowError, 'remote_operation_failed'):
                client.process(['ssh'], 1)
