"""Negative cases for ownership, PPS restoration and interrupted file updates."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'device'))
import native
import service
from ims_image import proven_owned_profiles, temporary_binary

UID='00000000-0000-0000-0000-000000000001'
OTHER='00000000-0000-0000-0000-000000000002'


class OwnershipTests(unittest.TestCase):
    def config(self, **kwargs):
        obj={'uid':UID,'name':'ims_123','adapter':'ims','owner':'ims_rrm','server_type':'ims'}
        obj.update(kwargs)
        return {'config':json.dumps(obj).encode()}

    def test_child_stdout_survives_ring_wrap(self):
        self.assertEqual(proven_owned_profiles(self.config(),set(),'', '  uid (string) '+UID+'\n',123),{UID:'ims_123'})

    def test_wrong_process_is_not_ownership(self):
        with self.assertRaises(AssertionError):
            proven_owned_profiles(self.config(),set(),'ims_rrm.456 vpn_login response: uid= '+UID,'',123)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(AssertionError):
            proven_owned_profiles(self.config(),set(),'','',123)

    def test_original_profile_is_never_deleted(self):
        self.assertEqual(proven_owned_profiles(self.config(),{UID.encode()},'','',123),{})

    def test_non_ims_profile_rejected(self):
        with self.assertRaises(AssertionError):
            proven_owned_profiles(self.config(adapter='ikev2'),set(),'','  uid (string) '+UID,123)

    def test_missing_original_profile_rejected(self):
        with self.assertRaises(AssertionError):
            proven_owned_profiles(self.config(),{OTHER.encode()},'','  uid (string) '+UID,123)

    def test_unknown_firmware_rejected(self):
        with self.assertRaises(AssertionError):
            temporary_binary(b'unknown firmware',True)


class RestoreTests(unittest.TestCase):
    def test_restore_preserves_unrelated_new_fields(self):
        before={p:{k:None for k in fields} for p,fields in service.UPDATES.items()}
        before[service.CDSC]['cdsc_xml']=':'
        data={p:dict(fields, unrelated=':owner-edit') for p,fields in service.UPDATES.items()}
        service.j={'pps_before':before,'original_voice_policy':0,'managed_files':{}}
        policy=[3]; writes=[]
        def read(p): return data[p]
        def update(p,fields):
            writes.append((p,fields))
            for k,v in fields.items():
                if v is None: data[p].pop(k,None)
                else: data[p][k]=v
        def setter(v):
            self.assertEqual(v,4); policy[0]=0
            return {'rc':0}
        with patch.object(service,'stop_native'),patch.object(service,'remove_owned'),patch.object(service,'save_journal'),patch.object(service,'status'),patch.object(service.os.path,'exists',return_value=False),patch.object(native,'read',side_effect=read),patch.object(native,'attrs',side_effect=lambda x:x),patch.object(native,'update_pps',side_effect=update),patch.object(native,'crypto_policy',return_value={'swcr_id':-1,'crypto_support':0}),patch.object(native,'voice_policy',side_effect=lambda:policy[0]),patch.object(service,'set_voice_preference',side_effect=setter),patch.object(service.time,'sleep'):
            service.restore()
        self.assertEqual(len(writes),3)
        self.assertTrue(service.j['restore_completed'])
        self.assertTrue(all(x['unrelated']==':owner-edit' for x in data.values()))

    def test_file_changed_by_another_owner_is_preserved(self):
        path=service.RUNTIME+'/ims_rrm'
        service.j={'managed_files':{path:hashlib.sha256(b'ours').hexdigest()}}
        with patch.object(service.os.path,'exists',return_value=True),patch.object(native,'read',return_value=b'changed'),patch.object(native,'atomic') as write:
            with self.assertRaises(AssertionError): service.write_owned(path,b'new',0o755)
            write.assert_not_called()

    def test_interrupted_write_accepts_previous_owned_bytes(self):
        path=service.RUNTIME+'/ims_rrm'
        service.j={'managed_files':{path:hashlib.sha256(b'new').hexdigest()},
                   'pending_previous_file_hashes':{path:hashlib.sha256(b'old').hexdigest()}}
        with patch.object(service.os.path,'exists',return_value=True),patch.object(native,'read',return_value=b'old'),patch.object(native,'atomic') as write,patch.object(service,'save_journal'):
            service.write_owned(path,b'new',0o755)
            write.assert_called_once_with(path,b'new',0o755)
        self.assertNotIn(path,service.j['pending_previous_file_hashes'])

    def test_owned_writer_cannot_target_stock_binary(self):
        with self.assertRaises(AssertionError): service.write_owned('/radio/bin/ims_rrm',b'new',0o755)


class NativeCommandTests(unittest.TestCase):
    def test_large_stdout_and_stderr_do_not_block_wait(self):
        data=native.command([sys.executable,'-c',
            'import sys;sys.stdout.write("a"*262144);sys.stderr.write("b"*262144)'],5)
        self.assertEqual(data,b'a'*262144)

    def test_native_timeout_kills_the_owned_child(self):
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            native.command([sys.executable,'-c','import time;time.sleep(5)'],0.1)


class PlatformRebootTests(unittest.TestCase):
    def test_owned_empty_pps_after_reboot_can_be_removed(self):
        with patch.object(service.os.path,'exists',return_value=True),patch.object(service.os.path,'islink',return_value=False),patch.object(service.os,'listdir',return_value=['ims']),patch.object(native,'read',return_value=b'@ims\n'),patch.object(service.os,'unlink') as unlink,patch.object(service.os,'rmdir') as rmdir:
            service.remove_platform()
            unlink.assert_called_once_with(service.CFG)
            rmdir.assert_called_once_with(service.CFG_DIR)

    def test_unknown_platform_field_is_preserved(self):
        with patch.object(service.os.path,'exists',return_value=True),patch.object(service.os.path,'islink',return_value=False),patch.object(service.os,'listdir',return_value=['ims']),patch.object(native,'read',return_value=b'@ims\nowner_setting::keep\n'),patch.object(service.os,'unlink') as unlink:
            with self.assertRaises(AssertionError):service.remove_platform()
            unlink.assert_not_called()


if __name__=='__main__':
    unittest.main()
