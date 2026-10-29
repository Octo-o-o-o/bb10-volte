"""Loopback mirrors exercise ranking, failover and byte-safe cross-origin resume."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fetch_materials as f


class MirrorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.data = bytes(range(251)) * 6000
        self.requests, self.messages, self.behaviors = [], [], {}
        self.slow_nodes = {'trickle'}
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                node = self.path.strip('/')
                headers = dict(self.headers)
                probe = headers.get('Range') == f'bytes=0-{f.PROBE_BYTES - 1}'
                fixture.requests.append((node, probe, headers))
                behavior = fixture.behaviors.get(node)
                response = behavior(headers, probe) if behavior else None
                status, values, body = response or fixture.normal(node, headers)
                self.send_response(status)
                for key, value in values.items():
                    self.send_header(key, str(value))
                self.end_headers()
                try:
                    if node in fixture.slow_nodes and not probe:
                        for offset in range(0, len(body), 4096):
                            self.wfile.write(body[offset:offset + 4096])
                            self.wfile.flush()
                            threading.Event().wait(0.02)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.item = {'file': 'firmware.7z', 'url': base + '/first', 'mirrors': [base + '/second', base + '/third'],
                     'size': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest()}
        self.target, self.partial = f._input_paths(self.item, self.folder)
        self.meta = self.partial.with_name(self.partial.name + '.json')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for mocker in (patch.object(f.urllib.request, 'build_opener', return_value=opener),
                       patch.object(f, 'ATTEMPTS', 3)):
            mocker.start()
            self.addCleanup(mocker.stop)

    def normal(self, node, headers):
        value = headers.get('Range')
        start, end = 0, len(self.data) - 1
        if value:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', value)
            start = int(match[1])
            end = min(end, int(match[2])) if match[2] else end
        if start >= len(self.data):
            return 416, {}, b''
        body = self.data[start:end + 1]
        values = {'Content-Length': len(body), 'ETag': '"' + node + '"'}
        if value:
            values['Content-Range'] = f'bytes {start}-{end}/{len(self.data)}'
        return 206 if value else 200, values, body

    def fetch(self, rank=True, **kwargs):
        if rank:
            return f.fetch_entries([self.item], self.folder, self.messages.append, **kwargs)
        with patch.object(f, '_rank_sources', side_effect=lambda item, urls, *args: urls):
            return f.fetch_entries([self.item], self.folder, self.messages.append, **kwargs)

    def transfers(self):
        return [(node, headers) for node, probe, headers in self.requests if not probe]

    def assert_complete(self):
        self.assertEqual(self.target.read_bytes(), self.data)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.meta.exists())

    def disconnect_first(self, cut=400000):
        self.behaviors['first'] = lambda headers, probe: None if probe else (
            200, {'Content-Length': len(self.data), 'ETag': '"first"'}, self.data[:cut])
        return cut

    def test_fastest_payload_probe_wins_over_manifest_order(self):
        def slow(headers, probe):
            if probe:
                threading.Event().wait(0.12)
        self.behaviors.update(first=slow, third=slow)
        self.fetch()
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['second'])
        self.assertEqual(sum(probe for _, probe, _ in self.requests), 3)
        self.assertTrue(any('测速' in line for line in self.messages))

    def test_failed_probes_do_not_prevent_successful_download(self):
        for node in ('first', 'second', 'third'):
            self.behaviors[node] = lambda headers, probe: (503, {}, b'') if probe else None
        self.fetch()
        self.assert_complete()

    def test_probe_deadline_does_not_wait_for_stuck_worker(self):
        release = threading.Event()
        self.addCleanup(release.set)
        def probe(item, url, opener, headers):
            if url.endswith('/first'):
                release.wait(2)
            return 123
        with patch.object(f, '_probe_source', side_effect=probe), patch.object(f, 'PROBE_DEADLINE', 0.05):
            started = time.monotonic()
            self.fetch()
            self.assertLess(time.monotonic() - started, 1)
        release.set()
        self.assert_complete()

    def test_disconnect_switches_and_resumes_with_overlap_not_foreign_etag(self):
        cut = self.disconnect_first()
        self.fetch(rank=False)
        self.assert_complete()
        transfers = self.transfers()
        self.assertEqual([node for node, _ in transfers], ['first', 'second'])
        self.assertEqual(transfers[1][1]['Range'], f'bytes={cut - f.OVERLAP_BYTES}-')
        self.assertNotIn('If-Range', transfers[1][1])
        self.assertTrue(any('切换节点' in line for line in self.messages))

    def test_cross_origin_overlap_mismatch_preserves_prefix_for_next_mirror(self):
        cut = self.disconnect_first()
        def bad_overlap(headers, probe):
            status, values, body = self.normal('second', headers)
            return status, values, b'x' + body[1:]
        self.behaviors['second'] = bad_overlap
        self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['first', 'second', 'third'])
        self.assertEqual(self.transfers()[2][1]['Range'], f'bytes={cut - f.OVERLAP_BYTES}-')

    def test_wrong_total_or_unsatisfied_range_does_not_destroy_saved_prefix(self):
        for status, values in ((416, {}), (206, {'Content-Range': 'bytes 0-9/10', 'Content-Length': '10'})):
            with self.subTest(status=status):
                self.disconnect_first()
                self.behaviors['second'] = lambda headers, probe: (status, values, b'0123456789')
                self.fetch(rank=False)
                self.assert_complete()
                self.target.unlink()

    def test_http_rejection_and_tls_failure_skip_to_other_mirrors(self):
        import ssl
        import urllib.error
        opener = urllib.request.build_opener()
        original = opener.open
        def open_url(request, **kwargs):
            if request.full_url.endswith('/first'):
                raise urllib.error.URLError(ssl.SSLCertVerificationError('redacted proxy detail'))
            return original(request, **kwargs)
        self.behaviors['second'] = lambda headers, probe: (404, {}, b'not found')
        with patch.object(opener, 'open', side_effect=open_url):
            self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['second', 'third'])
        self.assertFalse(any('redacted proxy' in message for message in self.messages))

    def test_retry_after_does_not_delay_a_healthy_alternative(self):
        self.behaviors['first'] = lambda headers, probe: (429, {'Retry-After': '60'}, b'')
        with patch.object(f.time, 'sleep') as sleep:
            self.fetch(rank=False)
        sleep.assert_not_called()
        self.assert_complete()

    def test_corrupt_complete_mirror_is_rejected_and_fresh_mirror_used(self):
        self.behaviors['first'] = lambda headers, probe: (
            200, {'Content-Length': len(self.data)}, b'x' * len(self.data))
        self.fetch(rank=False)
        self.assert_complete()
        self.assertNotIn('Range', self.transfers()[1][1])

    def test_slow_stream_switches_and_preserves_progress(self):
        self.item['url'] = self.item['url'].replace('/first', '/trickle')
        with patch.object(f, 'SLOW_WINDOW', 0.04), patch.object(f, 'MIN_SPEED', 1024 * 1024):
            self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['trickle', 'second'])
        self.assertIn('Range', self.transfers()[1][1])
        self.assertTrue(any('持续低速' in message for message in self.messages))

    def test_exhaustion_keeps_progress_and_next_run_uses_other_source(self):
        cut = self.disconnect_first()
        self.behaviors['second'] = self.behaviors['third'] = lambda h, p: (503, {}, b'')
        with patch.object(f.time, 'sleep'), self.assertRaises(f.DownloadError):
            self.fetch(rank=False)
        self.assertEqual(self.partial.read_bytes(), self.data[:cut])
        self.behaviors.clear()
        self.item['url'], self.item['mirrors'][0] = self.item['mirrors'][0], self.item['url']
        self.fetch(rank=False)
        self.assert_complete()
        self.assertNotIn('If-Range', self.transfers()[-1][1])

    def test_all_slow_nodes_eventually_settle_without_endless_switching(self):
        self.data = self.data[:128 * 1024]
        self.item.update(size=len(self.data), sha256=hashlib.sha256(self.data).hexdigest())
        self.target, self.partial = f._input_paths(self.item, self.folder)
        self.meta = self.partial.with_name(self.partial.name + '.json')
        self.slow_nodes = {'first', 'second', 'third'}
        with patch.object(f, 'SLOW_WINDOW', 0.04), patch.object(f, 'MIN_SPEED', 1024 * 1024), patch.object(f.time, 'sleep'):
            self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['first', 'second', 'third', 'first'])

    def test_cached_or_offline_inputs_never_probe_mirrors(self):
        with patch.object(f, '_rank_sources') as rank:
            with self.assertRaises(FileNotFoundError):
                self.fetch(verify_only=True)
            self.target.write_bytes(self.data)
            self.fetch()
            rank.assert_not_called()
        self.assertEqual(self.requests, [])

    def test_damaged_saved_tail_can_recover_from_clean_download(self):
        self.partial.write_bytes(self.data[:200000] + b'damaged tail')
        self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual(len(self.transfers()), 4)
        self.assertNotIn('Range', self.transfers()[-1][1])
        self.assertEqual(len(list(self.folder.glob('*.invalid-*'))), 1)

    def test_bad_old_prefix_does_not_blacklist_healthy_finishing_source(self):
        self.partial.write_bytes(b'damaged prefix' + self.data[14:400000])
        self.fetch(rank=False)
        self.assert_complete()
        self.assertEqual([node for node, _ in self.transfers()], ['first', 'first'])
        self.assertNotIn('Range', self.transfers()[-1][1])

    def test_cross_origin_requests_do_not_forward_authorization(self):
        self.behaviors['first'] = lambda h, p: (403, {}, b'')
        self.item['mirrors'] = [self.item['mirrors'][0].replace('127.0.0.1', 'localhost')]
        self.fetch(rank=False, headers={'Authorization': 'Bearer test-only', 'Cookie': 'test-only'})
        self.assert_complete()
        self.assertIn('Authorization', self.transfers()[0][1])
        self.assertNotIn('Authorization', self.transfers()[1][1])
        self.assertNotIn('Cookie', self.transfers()[1][1])


if __name__ == '__main__':
    unittest.main()
