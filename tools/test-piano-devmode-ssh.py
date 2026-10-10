#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Argument handling and link discovery of piano-devmode-ssh.py on a synthetic sysfs."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('devmode_ssh', Path(__file__).with_name('piano-devmode-ssh.py'))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
NETWORK = tool.load_network()


class FakeSysfs:
    """/sys/class/net entries whose device link resolves below a USB device directory."""

    def __init__(self, root):
        self.root = Path(root)
        self.net = self.root / 'class/net'
        self.net.mkdir(parents=True)

    def add(self, name, mac, vid='1d6b', pid='0104', serial='piano-abc123', usb=True):
        usbdev = self.root / f'devices/usb1/1-{name}'
        iface = usbdev / f'1-{name}:1.0'
        iface.mkdir(parents=True)
        if usb:
            for attr, value in (('idVendor', vid), ('idProduct', pid), ('serial', serial)):
                (usbdev / attr).write_text(value + '\n')
        netdev = self.net / name
        netdev.mkdir()
        (netdev / 'address').write_text(mac + '\n')
        (netdev / 'device').symlink_to(iface)


def routes(dev, prefsrc, returncode=0):
    def run(cmd, **kwargs):
        if cmd[:3] == ['ip', '-j', 'route']:
            assert cmd[4] == NETWORK['device_ip']
            out = json.dumps([{'dst': NETWORK['device_ip'], 'dev': dev, 'prefsrc': prefsrc}])
            return subprocess.CompletedProcess(cmd, returncode, out, '')
        run.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, '', '')
    run.calls = []
    return run


class Devmode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sys = FakeSysfs(self.tmp.name)
        self.exec = []

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, argv, run, euid=1000):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tool.main(argv, sys_net=self.sys.net, run=run, execvp=lambda f, a: self.exec.append(a),
                           clock=iter(range(0, 10000)).__next__, sleep=lambda s: None, euid=lambda: euid)
        return rc, out.getvalue(), err.getvalue()

    def test_network_contract_is_the_debug_channel_one(self):
        self.assertEqual(NETWORK, {'device_ip': '192.168.88.2', 'host_ip': '192.168.88.10',
                                   'device_mac': '02:00:00:88:00:02', 'host_mac': '02:00:00:88:00:01'})

    def test_finds_only_the_piano_ncm_link(self):
        self.sys.add('enx020000880001', NETWORK['host_mac'])
        self.sys.add('enxother', '02:00:00:88:00:09')
        self.sys.add('enxwrongid', NETWORK['host_mac'], pid='a4a2')
        self.sys.add('enxnotpiano', NETWORK['host_mac'], serial='other-1')
        self.sys.add('pci0', NETWORK['host_mac'], usb=False)
        self.assertEqual(tool.find_interfaces(NETWORK, sys_net=self.sys.net), [('enx020000880001', 'piano-abc123')])

    def test_serial_selects_one_of_two_tablets(self):
        self.sys.add('a', NETWORK['host_mac'], serial='piano-one')
        self.sys.add('b', NETWORK['host_mac'], serial='piano-two')
        self.assertEqual(tool.find_interfaces(NETWORK, 'two', self.sys.net), [('b', 'piano-two')])
        rc, _, err = self.main(['user'], routes('a', NETWORK['host_ip']))
        self.assertEqual(rc, 1)
        self.assertIn('more than one piano NCM link', err)
        rc, _, _ = self.main(['--serial', 'two', 'user'], routes('b', NETWORK['host_ip']))
        self.assertEqual((rc, self.exec), (1, [['ssh', 'user@192.168.88.2']]))

    def test_route_must_use_the_link_and_host_address(self):
        self.assertTrue(tool.route_ready('usb1', NETWORK, routes('usb1', '192.168.88.10')))
        self.assertFalse(tool.route_ready('usb1', NETWORK, routes('wlan0', '192.168.88.10')))
        self.assertFalse(tool.route_ready('usb1', NETWORK, routes('usb1', '192.168.88.11')))
        self.assertFalse(tool.route_ready('usb1', NETWORK, routes('usb1', '192.168.88.10', returncode=2)))

    def test_ssh_command_line(self):
        self.sys.add('usb1', NETWORK['host_mac'])
        run = routes('usb1', NETWORK['host_ip'])
        self.main(['user'], run)
        self.main(['-t', 'user', 'sudo', 'piano-reboot-bootloader'], run)
        self.main(['--wait', '0', 'user', '--', 'ls', '-l'], run)
        self.assertEqual(self.exec, [['ssh', 'user@192.168.88.2'],
                                     ['ssh', '-t', 'user@192.168.88.2', 'sudo', 'piano-reboot-bootloader'],
                                     ['ssh', 'user@192.168.88.2', 'ls', '-l']])
        self.assertEqual(run.calls, [])

    def test_check_reports_without_ssh(self):
        self.sys.add('usb1', NETWORK['host_mac'])
        rc, out, _ = self.main(['--check'], routes('usb1', NETWORK['host_ip']))
        self.assertEqual((rc, self.exec), (0, []))
        self.assertIn('usb1 piano-abc123 192.168.88.10 -> 192.168.88.2 ready', out)

    def test_bad_arguments(self):
        for argv in ([], ['-oProxyCommand=sh'], ['root@other'], ['--check', 'user'], ['--wait', '301', 'user'],
                     ['--wait', '-1', 'user'], ['']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as e:
                    tool.parse_args(argv)
                self.assertEqual(e.exception.code, 2)

    def test_no_link(self):
        rc, _, err = self.main(['--wait', '3', 'user'], routes('usb1', NETWORK['host_ip']))
        self.assertEqual((rc, self.exec), (1, []))
        self.assertIn('no piano NCM link', err)

    def test_missing_dhcp_lease_prints_the_ip_commands(self):
        self.sys.add('enx020000880001', NETWORK['host_mac'])
        rc, _, err = self.main(['--wait', '2', 'user'], routes('enp3s0', '192.168.10.5'))
        self.assertEqual((rc, self.exec), (2, []))
        self.assertIn('  sudo ip link set dev enx020000880001 up\n'
                      '  sudo ip address replace 192.168.88.10/24 dev enx020000880001\n', err)

    def test_root_sets_the_host_address_itself(self):
        self.sys.add('usb1', NETWORK['host_mac'])
        state = {'configured': False}
        base = routes('usb1', NETWORK['host_ip'])

        def run(cmd, **kwargs):
            if cmd[:3] == ['ip', '-j', 'route'] and not state['configured']:
                return subprocess.CompletedProcess(cmd, 0, json.dumps([{'dev': 'enp3s0', 'prefsrc': 'x'}]), '')
            if cmd[:2] == ['ip', 'address']:
                state['configured'] = True
            return base(cmd, **kwargs)
        rc, _, _ = self.main(['--wait', '0', 'user'], run, euid=0)
        self.assertEqual(base.calls, [['ip', 'link', 'set', 'dev', 'usb1', 'up'],
                                      ['ip', 'address', 'replace', '192.168.88.10/24', 'dev', 'usb1']])
        self.assertEqual(self.exec, [['ssh', 'user@192.168.88.2']])


if __name__ == '__main__':
    unittest.main()
