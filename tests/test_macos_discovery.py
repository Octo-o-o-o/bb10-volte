"""Mac USB discovery remains bounded, anonymous and tied to one /30 peer."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'tools'))
import macos_discovery as m
import root_setup as r


class MacDiscoveryTests(unittest.TestCase):
    def process(self, data, code=0):
        child = MagicMock(stdout=io.BytesIO(data))
        child.wait.return_value = code
        child.__enter__.return_value = child
        return child

    def test_system_client_binds_usb_and_restricts_transport(self):
        child = self.process(b'<d><ModelName>SQC100-2</ModelName><PIN>private</PIN></d>\n200')
        with patch.object(r.sys,'platform','darwin'), patch.object(m.subprocess,'Popen',return_value=child) as spawn:
            self.assertEqual(r.discovery('169.254.48.93','169.254.48.94'),{'ModelName':'SQC100-2'})
        args, options = spawn.call_args
        command = args[0]
        self.assertEqual(command[:2],['/usr/bin/curl','--disable'])
        for flag,value in (('--proxy',''),('--noproxy','*'),('--proto','=http'),('--interface','169.254.48.94'),('--max-time','5')):
            self.assertEqual(command[command.index(flag)+1],value)
        self.assertNotIn('--location',command)
        self.assertNotIn('shell',options)
        child.kill.assert_not_called()

    def test_redirect_error_truncation_and_oversize_do_not_supply_identity(self):
        for data,code in ((b'<d/>\n302',0),(b'<d/>\n200',7),(b'<d/>',0),
                          (b'x'*(m.LIMIT+1)+b'\n200',0)):
            child = self.process(data,code)
            with self.subTest(code=code,bytes=len(data)), patch.object(m.subprocess,'Popen',return_value=child):
                self.assertEqual(m.read('169.254.0.1','169.254.0.2'),b'')
            if len(data)>m.LIMIT+4:
                child.kill.assert_called_once()

    def test_non_usb_or_mismatched_peers_never_start_client(self):
        with patch.object(m.subprocess,'Popen') as spawn:
            for peer,source in (('192.168.1.1','192.168.1.2'),('169.254.0.1','169.254.0.6'),
                                ('169.254.0.2','169.254.0.3'),('example.com','169.254.0.2'),
                                ('::1','169.254.0.2')):
                self.assertEqual(m.read(peer,source),b'')
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
