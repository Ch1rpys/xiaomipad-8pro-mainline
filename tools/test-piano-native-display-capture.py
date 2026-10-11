#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reject false native PASS using saved firmware-only evidence and explicit synthetic DRM readings."""
import importlib.util,json,shutil,tempfile,unittest
from pathlib import Path
T=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('native_capture',T/'piano-native-display-capture.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
F=T/'fixtures/boot-acceptance/fast-piano2-20261009'

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
