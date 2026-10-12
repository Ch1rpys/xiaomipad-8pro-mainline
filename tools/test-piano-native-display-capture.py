#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject false native PASS using saved firmware-only evidence and explicit synthetic DRM readings."""
import importlib.util,json,shutil,tempfile,unittest
import contextlib, ctypes, io, struct
from unittest import mock
from pathlib import Path
T=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('native_capture',T/'piano-native-display-capture.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
F=T/'fixtures/boot-acceptance/fast-piano2-20261009'

class NativeQuery(unittest.TestCase):
    def test_real_emitted_query_with_nonempty_unrequested_arrays(self):
        calls = []
        def ioctl(fd, command, data):
            calls.append(command & 255)
            if command & 255 == 0xa0:
                pointer = struct.unpack_from('<Q', data, 8)[0]
                if pointer:
                    self.assertEqual(struct.unpack_from('<4I', data, 32), (0, 1, 0, 0))
                    ctypes.memmove(pointer, struct.pack('<I', 103), 4)
                else:
                    struct.pack_into('<4I', data, 32, 1, 1, 2, 2)
            else:
                self.assertEqual(command & 255, 0xa1)
                struct.pack_into('<I', data, 32, 1)
                struct.pack_into('<H', data, 40, 3200)
                struct.pack_into('<H', data, 50, 2136)
                struct.pack_into('<I', data, 60, 144)
        def glob(pattern):
            return ['/sys/class/drm/card0'] if pattern == '/sys/class/drm/card[0-9]*' else []
        output = io.StringIO()
        with mock.patch('glob.glob', side_effect=glob), mock.patch('os.open', return_value=3), \
             mock.patch('os.close'), mock.patch('os.path.realpath', return_value='/drivers/msm_dpu'), \
             mock.patch.object(Path, 'read_text', return_value='20.0 0.0'), \
             mock.patch('fcntl.ioctl', side_effect=ioctl), contextlib.redirect_stdout(output):
            exec(m.NATIVE, {})
        state = json.loads(output.getvalue().split('NATIVE_JSON=', 1)[1])
        self.assertEqual(calls, [0xa0, 0xa0, 0xa1])
        self.assertEqual(state['errors'], [])
        self.assertEqual(state['crtcs'], [{'id': 103, 'card': 'card0', 'width': 3200,
                                         'height': 2136, 'hz': 144}])

class NativeVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)/'evidence';shutil.copytree(F,self.d)
    def native(self,hz=120,underrun=0,width=3200):
        # Synthetic API output on top of real historical budget transcripts.
        # This data cannot be cited as a kernel or device result.
        state={'uptime':198.0,'connectors':{'card0-DSI-1':{'status':'connected','enabled':'enabled'}},
               'crtcs':[{'width':width,'height':2136,'hz':hz}], 'errors':[],
               'encoders':[{'intf':i,'vsync':23000,'underrun':underrun,'frame_timeout':0} for i in (1,2)]}
        p=self.d/'root-0098s-scanout.txt';p.write_text(p.read_text()+'\nNATIVE_JSON='+json.dumps(state)+'\nNATIVE_DSI_ERRORS=0\n')
    def test_firmware_pass_is_not_native_pass(self):
        v=m.judge(self.d,'7.2.6-piano2')
        self.assertEqual(v['hardware_verdict'],'INCOMPLETE')
        self.assertIn('native_capture',v['unavailable'])
    def test_synthetic_native_api_and_saved_budgets(self):
        self.native();v=m.judge(self.d,'7.2.6-piano2')
        self.assertEqual(v['hardware_verdict'],'PASS',v['failed']+v['unavailable'])
        self.assertEqual(v['desktop_visual'],'PENDING_OPERATOR')
    def test_144_hz_mode_requires_144_hz_scanout(self):
        self.native(hz=144);v=m.judge(self.d,'7.2.6-piano2')
        self.assertTrue(any(n.startswith('intf_rate:') for n in v['failed']))
    def test_latched_native_underrun_fails(self):
        self.native(underrun=1);v=m.judge(self.d,'7.2.6-piano2')
        self.assertTrue(any(n.startswith('zero_underrun:') for n in v['failed']))
    def test_wrong_crtc_is_not_desktop_pass(self):
        self.native(width=1600);v=m.judge(self.d,'7.2.6-piano2')
        self.assertTrue(any(n.startswith('native_kms:') for n in v['failed']))

if __name__=='__main__':unittest.main()
