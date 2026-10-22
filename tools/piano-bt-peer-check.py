#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Host-side BlueZ/PipeWire peer acceptance.

The same file is copied to a private temporary directory on the SSH target.
Endpoint modes keep the BlueZ agent and its D-Bus connection alive, and restore
state on stdin EOF, SIGTERM, or the 15 minute session deadline.
"""
import argparse
import array
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave


def run(argv, timeout=25, check=True, **kw):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw)
    if check and p.returncode:
        raise RuntimeError(f"{shlex.join(argv)}: {p.returncode}: {p.stdout}{p.stderr}")
    return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def wait_for(fn, seconds=20):
    end = time.monotonic() + seconds
    while True:
        value = fn()
        if value:
            return value
        if time.monotonic() >= end:
            raise TimeoutError("condition not reached before deadline")
        time.sleep(0.2)  # Poll state, never repeat a pairing/connection request.


def plain(v):
    import dbus
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, (dbus.String, dbus.ObjectPath, dbus.Signature)):
        return str(v)
    if isinstance(v, (int, float)):
        return int(v) if isinstance(v, int) else float(v)
    return v


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Peer:
    """One persistent endpoint process, with serialized named test operations."""
    def __init__(self, argv, log):
        self.log = open(log, "w")
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.log, text=True, bufsize=1)

    def call(self, op, timeout=200, **args):
        self.p.stdin.write(json.dumps({"op": op, **args}) + "\n")
        self.p.stdin.flush()
        if not select.select([self.p.stdout], [], [], timeout)[0]:
            raise TimeoutError(f"endpoint operation {op}")
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f"endpoint exited during {op}, rc={self.p.poll()}")
        response = json.loads(line)
        if not response["ok"]:
            raise RuntimeError(response["error"])
        return response["value"]

    def close(self):
        try:
            self.p.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.p.wait(35)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            self.p.wait(35)
        self.log.close()


def endpoint(args):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    props_if = "org.freedesktop.DBus.Properties"
    adapter_if = "org.bluez.Adapter1"
    device_if = "org.bluez.Device1"
    adapter_path = "/org/bluez/" + args.adapter
    work = Path(args.work)
    work.mkdir(mode=0o700, exist_ok=True)
    loop = GLib.MainLoop()
    state = {"before": None, "peer": None, "agent": None, "discovery": False,
             "obex": None, "wp_config": None, "children": [], "restored": None}

    def obj(path, interface):
        return dbus.Interface(bus.get_object("org.bluez", path, introspect=False), interface)

    def objects():
        return plain(obj("/", "org.freedesktop.DBus.ObjectManager").GetManagedObjects())

    def device_path():
        return adapter_path + "/dev_" + state["peer"].replace(":", "_")

    def get(path, interface):
        return plain(obj(path, props_if).GetAll(interface))

    def set_prop(path, interface, key, value):
        obj(path, props_if).Set(interface, key, value, signature="ssv")

    def pw():
        # A registry change during pw-dump can append another JSON array even
        # without --monitor. Apply its updates/removals to the initial snapshot.
        data = run(["pw-dump"])["stdout"].lstrip()
        decoder, items = json.JSONDecoder(), {}
        while data:
            batch, end = decoder.raw_decode(data)
            data = data[end:].lstrip()
            for item in batch:
                key = item["id"]
                if "info" in item and item["info"] is None:
                    items.pop(key, None)
                    continue
                old = items.get(key, {})
                if "info" in item and "info" in old:
                    info = {**old["info"], **item["info"]}
                    for field in ("props", "params"):
                        if field in item["info"]:
                            info[field] = {**old["info"].get(field, {}), **item["info"][field]}
                    item = {**item, "info": info}
                items[key] = {**old, **item}
        return list(items.values())

    def audio_state():
        items = pw()
        return {"defaults": [o.get("metadata", []) for o in items
                             if o.get("props", {}).get("metadata.name") == "default"],
                "devices": [{"name": o["info"]["props"].get("device.name"),
                             "profile": o["info"].get("params", {}).get("Profile")}
                            for o in items if o["type"].endswith(":Device")],
                "nodes": [{"name": o["info"]["props"].get("node.name"),
                           "props": o["info"].get("params", {}).get("Props")}
                          for o in items if o["type"].endswith(":Node")
                          and o["info"]["props"].get("media.class", "").startswith("Audio/")]}

    def snapshot():
        data = objects()
        return {"adapter": data[adapter_path][adapter_if],
                "devices": {p: i[device_if] for p, i in data.items() if device_if in i},
                "obex_active": run(["systemctl", "--user", "is-active", "obex.service"], check=False)["stdout"].strip(),
                "obex_enabled": run(["systemctl", "--user", "is-enabled", "obex.service"], check=False)["stdout"].strip(),
                "audio": audio_state(),
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "kernel": os.uname().release,
                "keyboard_monitor": run(["systemctl", "show", "piano-kbd-monitor.service", "-p", "ActiveState", "-p", "MainPID", "-p", "ActiveEnterTimestampMonotonic"], check=False)["stdout"],
                "ram_safety_timer": run(["systemctl", "show", "piano-ram-safety-reboot3.timer", "-p", "LoadState", "-p", "ActiveState", "-p", "ActiveEnterTimestampMonotonic", "-p", "NextElapseUSecMonotonic"], check=False)["stdout"],
                "versions": run(["dpkg-query", "-W", "bluez", "bluez-obexd", "pipewire", "wireplumber", "libspa-0.2-bluetooth"], check=False)}

    class Agent(dbus.service.Object):
        def allow(self, device):
            if str(device) != device_path():
                raise dbus.exceptions.DBusException("not the test peer", name="org.bluez.Error.Rejected")
            with (work / "agent.jsonl").open("a") as f:
                f.write(json.dumps({"time": time.time(), "device": str(device)}) + "\n")

        @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
        def RequestAuthorization(self, device):
            self.allow(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
        def RequestConfirmation(self, device, passkey):
            self.allow(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
        def AuthorizeService(self, device, uuid):
            self.allow(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
        def RequestPinCode(self, device):
            raise dbus.exceptions.DBusException("legacy PIN unsupported", name="org.bluez.Error.Rejected")

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
        def RequestPasskey(self, device):
            raise dbus.exceptions.DBusException("passkey unsupported", name="org.bluez.Error.Rejected")

        @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
        def Cancel(self):
            pass

    def stop_children():
        for child, log in state["children"]:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(8)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(5)
            log.close()
        state["children"] = []

    def cleanup():
        if state["restored"] is not None:
            return state["restored"]
        errors = []

        def attempt(fn):
            try:
                fn()
            except Exception as e:
                errors.append(str(e))

        attempt(stop_children)
        if state["discovery"]:
            attempt(lambda: obj(adapter_path, adapter_if).StopDiscovery())
            state["discovery"] = False
        if state["peer"] and state["before"]:
            path = device_path()
            if path in objects() and path not in state["before"]["devices"]:
                attempt(lambda: obj(adapter_path, adapter_if).RemoveDevice(dbus.ObjectPath(path)))
        if state["agent"]:
            attempt(lambda: obj("/org/bluez", "org.bluez.AgentManager1").UnregisterAgent(dbus.ObjectPath("/piano/peer_agent")))
            state["agent"].remove_from_connection()
            state["agent"] = None
        if state["obex"]:
            if state["obex"].p.poll() is None:
                attempt(lambda: state["obex"].call("quit"))
            attempt(state["obex"].close)
            state["obex"] = None
        if state.get("obex_masked"):
            attempt(lambda: run(["systemctl", "--user", "unmask", "--runtime", "obex.service"]))
        if state.get("obex_stopped") and state["before"]["obex_active"] == "active":
            attempt(lambda: run(["systemctl", "--user", "start", "obex.service"]))
        if state["wp_config"]:
            attempt(state["wp_config"].unlink)
            attempt(lambda: run(["systemctl", "--user", "restart", "wireplumber.service"]))
            # Wait for the original device names, not arbitrary startup delays.
            names = {d["name"] for d in state["before"]["audio"]["devices"]}
            attempt(lambda: wait_for(lambda: names.issubset({d["name"] for d in audio_state()["devices"]})))
        if state["before"]:
            # WirePlumber can reapply its saved mixer values after restarting.
            # Restore the original host nodes explicitly when that changed them.
            for old in (state["before"]["audio"]["nodes"] if state["wp_config"] else []):
                if not old["props"]:
                    continue
                nodes = [o for o in pw() if o["type"].endswith(":Node") and
                         o.get("info", {}).get("props", {}).get("node.name") == old["name"]]
                if not nodes:
                    continue
                node = nodes[0]
                values = {k: old["props"][0][k] for k in
                          ("volume", "mute", "channelVolumes", "monitorVolumes", "monitorMute")
                          if k in old["props"][0]}
                current = node["info"].get("params", {}).get("Props", [{}])[0]
                if any(current.get(k) != v for k, v in values.items()):
                    attempt(lambda n=node, v=values: run(["pw-cli", "set-param", str(n["id"]), "Props", json.dumps(v)]))
            original = state["before"]["adapter"]
            for key in ("Discoverable", "Pairable", "DiscoverableTimeout", "PairableTimeout", "Powered"):
                if key in original:
                    value = original[key]
                    value = dbus.UInt32(value) if key.endswith("Timeout") else dbus.Boolean(value)
                    attempt(lambda k=key, v=value: set_prop(adapter_path, adapter_if, k, v))
            attempt(lambda: wait_for(lambda: set(get(adapter_path, adapter_if)["UUIDs"]) == set(original["UUIDs"]), 10))
        after = snapshot()
        before = state["before"]
        keys = ("Powered", "Discoverable", "Pairable", "DiscoverableTimeout", "PairableTimeout", "Alias", "Discovering")
        checks = {} if before is None else {
            "adapter": all(before["adapter"].get(k) == after["adapter"].get(k) for k in keys),
            "adapter_profiles": set(before["adapter"]["UUIDs"]) == set(after["adapter"]["UUIDs"]),
            "pairing_removed": not state["peer"] or device_path() not in after["devices"],
            "existing_bonds": {p for p, d in before["devices"].items() if d.get("Paired")} == {p for p, d in after["devices"].items() if d.get("Paired")},
            "obex_service": all(before[k] == after[k] for k in ("obex_active", "obex_enabled")),
            "same_boot": before["boot_id"] == after["boot_id"],
            "keyboard_monitor": before["keyboard_monitor"] == after["keyboard_monitor"],
            "ram_safety_timer": before["ram_safety_timer"] == after["ram_safety_timer"],
            "audio": before["audio"] == after["audio"],
            "temporary_processes": not state["children"] and state["obex"] is None,
            "temporary_rule_removed": state["wp_config"] is None or not state["wp_config"].exists(),
        }
        state["restored"] = {"checks": checks, "errors": errors, "after": after}
        (work / "restored.json").write_text(json.dumps(state["restored"], indent=2))
        return state["restored"]

    def dispatch(q):
        op = q["op"]
        if op == "snapshot":
            result = snapshot()
            if state["before"] is None:
                state["before"] = result
                (work / "before.json").write_text(json.dumps(result, indent=2))
            return result
        if op == "prepare":
            state["peer"] = q["peer"]
            if device_path() in state["before"]["devices"]:
                raise RuntimeError("peer already known: refusing to replace its pre-existing state")
            if state["before"]["adapter"].get("Discovering"):
                raise RuntimeError("adapter already discovering: refusing to disturb its session")
            state["agent"] = Agent(bus, "/piano/peer_agent")
            manager = obj("/org/bluez", "org.bluez.AgentManager1")
            manager.RegisterAgent(dbus.ObjectPath("/piano/peer_agent"), "NoInputNoOutput")
            manager.RequestDefaultAgent(dbus.ObjectPath("/piano/peer_agent"))
            for key, value in (("Powered", dbus.Boolean(True)), ("DiscoverableTimeout", dbus.UInt32(0)),
                               ("PairableTimeout", dbus.UInt32(0)), ("Pairable", dbus.Boolean(True)),
                               ("Discoverable", dbus.Boolean(True))):
                set_prop(adapter_path, adapter_if, key, value)
            return get(adapter_path, adapter_if)
        if op == "discover":
            obj(adapter_path, adapter_if).SetDiscoveryFilter(dbus.Dictionary({"Transport": "bredr"}, signature="sv"))
            obj(adapter_path, adapter_if).StartDiscovery()
            state["discovery"] = True
            try:
                return wait_for(lambda: objects().get(device_path(), {}).get(device_if), 30)
            finally:
                obj(adapter_path, adapter_if).StopDiscovery()
                state["discovery"] = False
        if op == "pair":
            obj(device_path(), device_if).Pair(timeout=55)
            return get(device_path(), device_if)
        if op == "trust":
            set_prop(device_path(), device_if, "Trusted", dbus.Boolean(True))
            return get(device_path(), device_if)
        if op in ("connect", "disconnect", "a2dp_connect"):
            dev = obj(device_path(), device_if)
            if op == "a2dp_connect":
                dev.ConnectProfile("0000110b-0000-1000-8000-00805f9b34fb", timeout=35)
            elif op == "connect":
                dev.Connect(timeout=35)
            else:
                dev.Disconnect(timeout=20)
            return get(device_path(), device_if)
        if op == "device":
            return get(device_path(), device_if)
        if op == "transports":
            return {p: i["org.bluez.MediaTransport1"] for p, i in objects().items()
                    if "org.bluez.MediaTransport1" in i and p.startswith(device_path() + "/")}
        if op == "host_audio_input":
            items = pw()
            if any(o.get("info", {}).get("props", {}).get("media.class", "").startswith("Stream/") for o in items):
                raise RuntimeError("host has live audio clients; cannot restart WirePlumber for test rule")
            version = run(["wireplumber", "--version"])["stdout"]
            root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "wireplumber"
            if "0.4." in version:
                path = root / "bluetooth.lua.d/99-piano-bt-peer-test.lua"
                content = 'bluez_monitor.properties["bluez5.roles"] = "[ a2dp_sink ]"\n'
                content += 'table.insert(bluez_monitor.rules, { matches = { { { "api.bluez5.address", "equals", "' + state["peer"] + '" }, { "api.bluez5.profile", "equals", "a2dp-source" } } }, apply_properties = { ["bluez5.media-source-role"] = "input", ["node.autoconnect"] = false } })\n'
            else:
                path = root / "wireplumber.conf.d/99-piano-bt-peer-test.conf"
                content = 'monitor.bluez.properties = { bluez5.roles = [ a2dp_sink ] }\n'
                content += 'monitor.bluez.rules = [ { matches = [ { api.bluez5.address = "' + state["peer"] + '" api.bluez5.profile = "a2dp-source" } ] actions = { update-props = { bluez5.media-source-role = "input" node.autoconnect = false } } } ]\n'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as f:
                f.write(content)
            state["wp_config"] = path
            run(["systemctl", "--user", "restart", "wireplumber.service"])
            sink_uuid = "0000110b-0000-1000-8000-00805f9b34fb"
            hf_uuids = {"0000111e-0000-1000-8000-00805f9b34fb", "0000111f-0000-1000-8000-00805f9b34fb"}
            wait_for(lambda: sink_uuid in get(adapter_path, adapter_if)["UUIDs"] and not hf_uuids.intersection(get(adapter_path, adapter_if)["UUIDs"]))
            return {"rule": str(path), "version": version}
        if op == "obex_start":
            # A private session bus isolates our receive agent from desktop UIs.
            # Refuse to interrupt any existing OBEX transfer.
            session = dbus.SessionBus()
            if session.name_has_owner("org.bluez.obex"):
                current = dbus.Interface(session.get_object("org.bluez.obex", "/"), "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
                if any("org.bluez.obex.Transfer1" in v or "org.bluez.obex.Session1" in v for v in current.values()):
                    raise RuntimeError("OBEX has an existing session/transfer")
            if state["before"]["obex_enabled"].startswith("masked"):
                raise RuntimeError("OBEX was masked before test")
            run(["systemctl", "--user", "mask", "--runtime", "obex.service"])
            state["obex_masked"] = True
            run(["systemctl", "--user", "stop", "obex.service"])
            state["obex_stopped"] = True
            state["obex"] = Peer(["dbus-run-session", "--", sys.executable, __file__, "--obex-endpoint", "--work", str(work / "obex"), "--peer", state["peer"]], work / "obex-agent.log")
            return state["obex"].call("ready")
        if op == "obex_send":
            if state["obex"] is None:
                raise RuntimeError("OBEX setup failed")
            return state["obex"].call("send", seconds=90)
        if op == "obex_received":
            return state["obex"].call("received")
        if op == "audio_profile":
            def find_card():
                return next((o for o in pw() if o["type"].endswith(":Device") and
                             o.get("info", {}).get("props", {}).get("api.bluez5.address", "").upper() == state["peer"]), None)
            card = wait_for(find_card)
            profiles = card["info"].get("params", {}).get("EnumProfile", [])
            profile = next((p for p in profiles if p.get("name") == q["profile"]), None)
            if profile is None:
                raise RuntimeError("required A2DP profile absent: " + json.dumps(profiles))
            run(["pw-cli", "set-param", str(card["id"]), "Profile", json.dumps({"index": profile["index"]})])
            return card
        if op == "audio_node":
            def find_node():
                for o in pw():
                    p = o.get("info", {}).get("props", {})
                    if o["type"].endswith(":Node") and p.get("media.class") == q["media_class"] and p.get("api.bluez5.address", "").upper() == state["peer"]:
                        return o
            return wait_for(find_node)
        if op == "record":
            log = (work / "pw-record.log").open("w")
            child = subprocess.Popen(["pw-record", "--target", q["target"], "--rate", "48000", "--channels", "2", "--format", "s16", "--properties", '{ node.name = "piano-bt-peer-record" node.dont-reconnect = true }', str(work / "received.wav")], stdout=log, stderr=log)
            state["children"].append((child, log))
            wait_for(lambda: any(o.get("info", {}).get("props", {}).get("node.name") == "piano-bt-peer-record" and o["info"].get("state") == "running" for o in pw()), 15)
            return {"pid": child.pid}
        if op == "play":
            rate = 48000
            # 1s silence, 10s tone, 1s silence supplies an in-stream noise floor.
            samples = array.array("h")
            for i in range(12 * rate):
                v = round(8192 * math.sin(2 * math.pi * 1000 * i / rate)) if rate <= i < 11 * rate else 0
                samples.extend((v, v))
            if sys.byteorder != "little":
                samples.byteswap()
            with wave.open(str(work / "tone.wav"), "wb") as f:
                f.setparams((2, 2, rate, 0, "NONE", "not compressed"))
                f.writeframes(samples.tobytes())
            log = (work / "pw-play.log").open("w")
            child = subprocess.Popen(["pw-play", "--raw", "--target", q["target"], "--rate", str(rate), "--channels", "2", "--format", "s16", "--properties", '{ node.name = "piano-bt-peer-play" node.dont-reconnect = true }', "-"], stdin=subprocess.PIPE, stdout=log, stderr=log)
            state["children"].append((child, log))
            state["tone_ready"] = threading.Event()

            def feed():
                try:
                    deadline = time.monotonic() + 30
                    # Incoming A2DP nodes appear only once the source streams.
                    # Pipe backpressure paces silence until recording is ready.
                    while not state["tone_ready"].is_set():
                        if time.monotonic() > deadline:
                            raise TimeoutError("recorder did not become ready")
                        child.stdin.write(bytes(960 * 4))
                        child.stdin.flush()
                    child.stdin.write(samples.tobytes())
                    child.stdin.close()
                except (BrokenPipeError, OSError, TimeoutError) as e:
                    print(str(e), file=sys.stderr)
                    try:
                        child.stdin.close()
                    except BrokenPipeError:
                        pass

            state["feeder"] = threading.Thread(target=feed, daemon=True)
            state["feeder"].start()
            return {"pid": child.pid, "sha256": sha(work / "tone.wav")}
        if op == "tone":
            state["tone_ready"].set()
            return {"tone_started_unix": time.time()}
        if op == "audio_finish":
            if q.get("wait_play"):
                child = state["children"][-1][0]
                rc = child.wait(22)
                if rc:
                    raise RuntimeError(f"pw-play failed: {rc}")
            else:
                stop_children()
            return {"files": [str(p) for p in work.glob("*.wav")], "pw": pw()}
        if op == "audio_stop":
            stop_children()
            return {"stopped": True}
        if op == "pw":
            return pw()
        if op == "cleanup":
            return cleanup()
        raise ValueError(op)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def request(line):
        try:
            request = json.loads(line)
            print(json.dumps({"op": request["op"], "started_unix": time.time()}), file=sys.stderr, flush=True)
            value = dispatch(request)
            print(json.dumps({"ok": True, "value": value}), flush=True)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"ok": False, "error": str(e)}), flush=True)

    def finish(*unused):
        def do_finish():
            try:
                cleanup()
            finally:
                GLib.idle_add(loop.quit)
        pool.submit(do_finish)
        return False

    def readable(fd, condition):
        line = sys.stdin.readline()
        if not line:
            return finish()
        pool.submit(request, line)
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, readable)
    GLib.timeout_add_seconds(900, finish)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, finish)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, finish)
    loop.run()
    pool.shutdown(wait=True)


def obex_endpoint(args):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    work = Path(args.work)
    work.mkdir(mode=0o700)
    log = (work / "obexd.log").open("w")
    binary = next(p for p in ("/usr/libexec/bluetooth/obexd", "/usr/lib/bluetooth/obexd") if Path(p).is_file())
    daemon = subprocess.Popen([binary, "--nodetach", "--root", str(work), "--plugin=opp,bluetooth,filesystem"], stdout=log, stderr=log)
    wait_for(lambda: bus.name_has_owner("org.bluez.obex"), 10)
    loop = GLib.MainLoop()
    transfers = {}

    def changed(interface, values, invalidated, path=None):
        if interface == "org.bluez.obex.Transfer1":
            transfers.setdefault(str(path), {}).update(plain(values))
            with (work / "transfers.jsonl").open("a") as f:
                f.write(json.dumps({"time": time.time(), "path": str(path), "changed": plain(values)}) + "\n")

    bus.add_signal_receiver(changed, signal_name="PropertiesChanged",
                            dbus_interface="org.freedesktop.DBus.Properties",
                            bus_name="org.bluez.obex", path_keyword="path")

    def iface(path, name):
        return dbus.Interface(bus.get_object("org.bluez.obex", path, introspect=False), name)

    def get(path, name):
        return plain(iface(path, "org.freedesktop.DBus.Properties").GetAll(name))

    class Receiver(dbus.service.Object):
        @dbus.service.method("org.bluez.obex.Agent1", in_signature="o", out_signature="s")
        def AuthorizePush(self, transfer):
            info = get(transfer, "org.bluez.obex.Transfer1")
            session = get(info["Session"], "org.bluez.obex.Session1")
            if session["Destination"].upper() != args.peer.upper() or info.get("Size") != 1048576:
                raise dbus.exceptions.DBusException("not test peer/payload", name="org.bluez.obex.Error.Rejected")
            (work / "incoming.json").write_text(json.dumps({"transfer": info, "session": session}, indent=2))
            return str(work / "received.bin")

        @dbus.service.method("org.bluez.obex.Agent1", in_signature="", out_signature="")
        def Cancel(self):
            pass

        @dbus.service.method("org.bluez.obex.Agent1", in_signature="", out_signature="")
        def Release(self):
            pass

    receiver = Receiver(bus, "/piano/obex_agent")
    iface("/org/bluez/obex", "org.bluez.obex.AgentManager1").RegisterAgent(dbus.ObjectPath("/piano/obex_agent"))
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def execute(q):
        if q["op"] == "ready":
            return {"pid": daemon.pid, "root": str(work)}
        if q["op"] == "quit":
            return {"stopped": True}
        if q["op"] == "received":
            f = work / "received.bin"
            wait_for(lambda: f.is_file() and f.stat().st_size == 1048576, 10)
            return {"bytes": f.stat().st_size, "sha256": sha(f)}
        if q["op"] == "send":
            f = work / "payload.bin"
            f.write_bytes(os.urandom(1048576))
            client = iface("/org/bluez/obex", "org.bluez.obex.Client1")
            session = client.CreateSession(args.peer, dbus.Dictionary({"Target": "opp"}, signature="sv"), timeout=35)
            try:
                transfer, initial = iface(session, "org.bluez.obex.ObjectPush1").SendFile(str(f))
                # obexd removes completed Transfer1 objects. Keep the terminal
                # PropertiesChanged signal instead of polling a vanished object.
                transfers[str(transfer)] = {**plain(initial), **transfers.get(str(transfer), {})}
                history = []
                end = time.monotonic() + q["seconds"]
                while time.monotonic() < end:
                    data = transfers[str(transfer)].copy()
                    history.append(data)
                    if data["Status"] == "error":
                        raise RuntimeError("OBEX transfer failed: " + json.dumps(data))
                    if data["Status"] == "complete":
                        return {"bytes": f.stat().st_size, "sha256": sha(f), "history": history}
                    time.sleep(0.25)
                raise TimeoutError("OBEX transfer deadline")
            finally:
                client.RemoveSession(session)
        raise ValueError(q["op"])

    def request(line):
        q = json.loads(line)
        try:
            print(json.dumps({"ok": True, "value": execute(q)}), flush=True)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"ok": False, "error": str(e)}), flush=True)
        if q["op"] == "quit":
            GLib.idle_add(loop.quit)

    def readable(fd, cond):
        line = sys.stdin.readline()
        if not line:
            loop.quit()
            return False
        pool.submit(request, line)
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, readable)
    try:
        loop.run()
    finally:
        pool.shutdown(wait=True)
        daemon.terminate()
        daemon.wait(10)
        log.close()


def analyse_audio(path):
    import numpy as np
    with wave.open(str(path), "rb") as f:
        rate, channels = f.getframerate(), f.getnchannels()
        if f.getsampwidth() != 2:
            raise RuntimeError("expected S16 recording")
        x = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(float).reshape(-1, channels).mean(axis=1) / 32768
    window = rate // 10
    rms = np.array([np.sqrt(np.mean(x[i:i+window]**2)) for i in range(0, len(x)-window, window)])
    if not len(rms) or rms.max() < 1e-5:
        raise RuntimeError("recording is silent/empty")
    tone = rms > rms.max() * 0.5
    duration = float(tone.sum() / 10)
    middle = int(np.argmax(rms) * window)
    segment = x[middle:middle + rate]
    spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
    freq = float(np.argmax(spectrum) * rate / len(segment))
    quiet = rms[~tone]
    if len(quiet) < 5:
        raise RuntimeError("less than 0.5s of recorded silence for noise measurement")
    noise = max(float(np.median(quiet)), 1 / (32768 * math.sqrt(12)))
    signal_rms = float(np.median(rms[tone]))
    snr = 20 * math.log10(signal_rms / noise)
    result = {"peak_hz": freq, "tone_seconds": duration, "recorded_seconds": len(x)/rate,
              "signal_rms": signal_rms, "noise_rms": noise, "signal_over_noise_db": snr,
              "method": "100ms RMS tone windows; median silence RMS with S16 quantization floor; 1s Hann FFT"}
    result["pass"] = abs(freq - 1000) <= 10 and snr >= 20 and 9.5 <= duration <= 10.5
    return result


def main(args):
    import fcntl
    import numpy  # Fail before changing state if the analysis dependency is absent.
    os.umask(0o077)
    lock = open(Path(os.environ["XDG_RUNTIME_DIR"]) / ("piano-bt-peer-" + args.adapter + ".lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", args.ssh]
    serial = args.serial
    identity = run(ssh + ["cat /proc/cmdline; cat /sys/firmware/devicetree/base/compatible; uname -r"])
    (out / "identity.json").write_text(json.dumps(identity, indent=2))
    if f"androidboot.serialno={serial}" not in identity["stdout"].split() or "xiaomi,piano" not in identity["stdout"]:
        raise RuntimeError("SSH target does not match requested piano serial")
    password = Path(args.sudo_password_file).read_text() if args.sudo_password_file else None

    def privileged(side, argv, timeout=20):
        command = ["sudo", "-S", "-p", ""] if side == "tablet" and password else ["sudo", "-n"]
        command += argv
        if side == "tablet":
            command = ssh + [shlex.join(command)]
        return run(command, timeout=timeout, check=False, input=password if side == "tablet" else None)

    remote_work = run(ssh + ["mktemp -d /tmp/piano-bt-peer.XXXXXXXX"])["stdout"].strip()
    remote_script = remote_work + "/peer.py"
    source = Path(__file__).read_text()
    frozen_script = out / "runner.py"
    frozen_script.write_text(source)
    (out / "inputs.json").write_text(json.dumps({"script_sha256": sha(frozen_script), "obex_requested": not (args.skip_obex or args.reconnect_only),
                                                "reconnect_only": args.reconnect_only, "reconnect_from": args.reconnect_from,
                                                "reconnect_count": args.reconnect_count,
                                                "reconnect_policy": args.reconnect_policy,
                                                "link_diagnostics": args.link_diagnostics,
                                                "started_unix": time.time()}, indent=2))
    run(ssh + ["cat > " + shlex.quote(remote_script)], input=source)
    host_work = out / "host"
    host_work.mkdir()
    peers = {}
    results = {}
    policy_restore = {}
    mode_restore = {}

    def report(name, fn):
        started = time.time()
        try:
            value = fn()
            result = {"status": "PASS", "evidence": value}
            if isinstance(value, dict) and value.get("pass") is False:
                result["status"] = "FAIL"
        except Exception as e:
            result = {"status": "FAIL", "error": str(e)}
        result["started_unix"] = started
        result["elapsed_seconds"] = time.time() - started
        results[name] = result
        (out / "results.json").write_text(json.dumps(results, indent=2))
        # Raw addresses remain only in the private evidence directory.
        print(json.dumps({"item": name, "status": result["status"], "evidence": str(out / "results.json")}), flush=True)
        return result

    def both(op, **kw):
        return {side: peer.call(op, **kw) for side, peer in peers.items()}

    def ping(side):
        dest = address["host" if side == "tablet" else "tablet"]
        value = privileged(side, ["l2ping", "-i", args.adapter, "-c", "5", "-t", "3", dest], timeout=22)
        value["pass"] = value["rc"] == 0 and bool(re.search(r"\b5 sent, 5 received, 0% loss\b", value["stdout"]))
        return value

    def policy(side):
        value = privileged(side, ["hciconfig", args.adapter, "lp"])
        match = re.search(r"Link policy:\s*([^\n]*)", value["stdout"])
        if value["rc"] or not match:
            raise RuntimeError("cannot read default link policy")
        return match[1].strip().split()

    def change_policy():
        if args.reconnect_policy == "default" or policy_restore:
            return
        side = "host" if args.reconnect_policy == "host-no-sniff" else "tablet"
        original = policy(side)
        remove = "RSWITCH" if args.reconnect_policy == "tablet-no-role-switch" else "SNIFF"
        target = [v for v in original if v != remove]
        if not target or target == original:
            raise RuntimeError("requested policy bit absent or empty resulting policy")
        policy_restore[side] = original
        if remove == "RSWITCH":
            # Linux Create_Connection Allow_Role_Switch is derived from link
            # mode, not the default link-policy bit. Cover connection setup
            # too; otherwise disabling RSWITCH alone does not test the role.
            value = privileged(side, ["hciconfig", args.adapter, "lm"])
            match = re.search(r"Link mode:\s*([^\n]*)", value["stdout"])
            if value["rc"] or not match:
                raise RuntimeError("cannot read default link mode")
            mode_restore[side] = match[1].strip().split()
            target_mode = sorted((set(mode_restore[side]) - {"PERIPHERAL"}) | {"CENTRAL"})
            value = privileged(side, ["hciconfig", args.adapter, "lm", ",".join(target_mode).lower()])
            mode_after = privileged(side, ["hciconfig", args.adapter, "lm"])
            if value["rc"] or "CENTRAL" not in mode_after["stdout"]:
                raise RuntimeError("cannot prohibit setup role switch")
            (out / "mode-control.json").write_text(json.dumps({"side": side,
                "before": mode_restore[side], "after": mode_after, "command": value}, indent=2))
        result = privileged(side, ["hciconfig", args.adapter, "lp", ",".join(target).lower()])
        after = policy(side)
        (out / "policy-control.json").write_text(json.dumps({"side": side, "before": original,
            "requested": target, "after": after, "command": result}, indent=2))
        if result["rc"] or after != target:
            raise RuntimeError("link policy readback mismatch")

    def link_diagnostics(label):
        # Read only, after measured pings so the observation cannot wake the
        # controller before the connectivity measurement.
        data = {}
        for side in peers:
            dest = address["host" if side == "tablet" else "tablet"]
            data[side] = {op: privileged(side, ["hcitool", "-i", args.adapter, op, dest])
                          for op in ("lp", "lst", "afh", "rssi", "lq")}
            data[side]["connections"] = privileged(side, ["hcitool", "-i", args.adapter, "con"])
        (out / (label + "-links.json")).write_text(json.dumps(data, indent=2))
        return {"links": data, "pass": all(v["rc"] == 0 for d in data.values() for v in d.values())}

    try:
        peers["host"] = Peer([sys.executable, str(frozen_script), "--endpoint", "--adapter", args.adapter, "--work", str(host_work)], out / "host-endpoint.log")
        peers["tablet"] = Peer(ssh + [shlex.join(["/usr/bin/python3", remote_script, "--endpoint", "--adapter", args.adapter, "--work", remote_work + "/tablet"])], out / "tablet-endpoint.log")
        before = both("snapshot")
        (out / "before.json").write_text(json.dumps(before, indent=2))
        address = {side: data["adapter"]["Address"].upper() for side, data in before.items()}
        timer = before["tablet"]["ram_safety_timer"]
        if "LoadState=loaded" in timer and "ActiveState=active" not in timer:
            raise RuntimeError("existing RAM safety timer is not active")
        for side, data in before.items():
            peer_path = "/org/bluez/" + args.adapter + "/dev_" + address["tablet" if side == "host" else "host"].replace(":", "_")
            if peer_path in data["devices"]:
                raise RuntimeError("test peer already known; preserving its original state")
            (out / (side + "-kernel-inputs.json")).write_text(json.dumps(privileged(side, ["sha256sum", "/boot/vmlinuz-" + data["kernel"], "/boot/config-" + data["kernel"]]), indent=2))
        report("power_discoverable", lambda: {side: peers[side].call("prepare", peer=address["tablet" if side == "host" else "host"]) for side in peers})
        audio_ready = report("host_audio_setup", lambda: peers["host"].call("host_audio_input"))
        report("discovery_tablet", lambda: peers["tablet"].call("discover"))
        report("discovery_host", lambda: peers["host"].call("discover"))
        report("pair", lambda: peers["tablet"].call("pair"))
        report("trust", lambda: both("trust"))
        report("connect", lambda: peers["tablet"].call("connect"))
        report("l2ping_tablet_host", lambda: ping("tablet"))
        report("l2ping_host_tablet", lambda: ping("host"))
        if args.link_diagnostics:
            report("initial_link_diagnostics", lambda: link_diagnostics("initial"))
        for side in peers:
            def rssi(s=side):
                dest = address["host" if s == "tablet" else "tablet"]
                value = privileged(s, ["hcitool", "-i", args.adapter, "rssi", dest])
                value["pass"] = value["rc"] == 0 and "RSSI return value:" in value["stdout"]
                return value
            report("rssi_" + side, rssi)
        if not args.skip_obex and not args.reconnect_only:
            for side in peers:
                report("obex_setup_" + side, lambda s=side: peers[s].call("obex_start"))
            for source, target in (("tablet", "host"), ("host", "tablet")):
                def transfer(s=source, t=target):
                    sent = peers[s].call("obex_send")
                    received = peers[t].call("obex_received")
                    return {"sent": sent, "received": received,
                            "pass": sent["sha256"] == received["sha256"] and received["bytes"] == 1048576}
                report("obex_" + source + "_" + target, transfer)

        def audio_check():
            if audio_ready["status"] != "PASS":
                raise RuntimeError("host audio input setup failed")
            evidence = {}
            def save():
                (out / "a2dp-progress.json").write_text(json.dumps(evidence, indent=2))
            # Explicit A2DP profile bypasses HFP/HSP auto-selection.
            evidence["connect"] = peers["tablet"].call("a2dp_connect")
            save()
            # PipeWire calls a remote source's receiving profile audio-gateway.
            evidence["host_card"] = peers["host"].call("audio_profile", profile="audio-gateway")
            save()
            evidence["tablet_card"] = peers["tablet"].call("audio_profile", profile="a2dp-sink")
            save()
            sink = peers["tablet"].call("audio_node", media_class="Audio/Sink")
            evidence["play"] = peers["tablet"].call("play", target=sink["info"]["props"]["node.name"])
            src = peers["host"].call("audio_node", media_class="Audio/Source")
            evidence["nodes"] = {"host": src, "tablet": sink}
            evidence["codec"] = {"host": src["info"]["props"].get("api.bluez5.codec"),
                                 "tablet": sink["info"]["props"].get("api.bluez5.codec")}
            save()
            evidence["record"] = peers["host"].call("record", target=src["info"]["props"]["node.name"])
            evidence["tone"] = peers["tablet"].call("tone")
            evidence["transports"] = both("transports")
            save()
            evidence["tablet_finish"] = peers["tablet"].call("audio_finish", wait_play=True)
            evidence["host_finish"] = peers["host"].call("audio_finish")
            evidence["analysis"] = analyse_audio(host_work / "received.wav")
            evidence["pass"] = evidence["analysis"]["pass"] and all(evidence["transports"].values())
            save()
            return evidence
        if not args.reconnect_only:
            audio_result = report("a2dp", audio_check)
            if audio_result["status"] != "PASS":
                (out / "audio-failure-pw.json").write_text(json.dumps(both("pw"), indent=2))
                (out / "audio-failure-transports.json").write_text(json.dumps(both("transports"), indent=2))
            report("audio_stream_cleanup", lambda: both("audio_stop"))

        def reconnect():
            prior = both("device")
            if not all(d.get("Paired") and d.get("Bonded") for d in prior.values()):
                raise RuntimeError("reconnect requires both peers already bonded; a new pairing is not a reconnect")
            peers["tablet"].call("disconnect")
            def disconnected_state():
                states = both("device")
                return states if not any(d["Connected"] for d in states.values()) else None
            disconnected = wait_for(disconnected_state, 15)
            change_policy()
            peers[args.reconnect_from].call("connect")
            after = both("device")
            return {"before": prior, "disconnected": disconnected, "after": after,
                    "pass": all(d.get("Paired") and d.get("Connected") for d in after.values())}
        for cycle in range(1, args.reconnect_count + 1):
            suffix = "" if cycle == 1 else "_" + str(cycle)
            control = report("reconnect_without_pair" + suffix, reconnect)
            if control["status"] != "PASS":
                # l2ping itself can create an unauthenticated replacement ACL.
                # Never turn a failed profile reconnect into a false ping PASS.
                def failed_prerequisite():
                    raise RuntimeError("not measured: bonded profile reconnection failed")
                report("reconnect_l2ping" + suffix, failed_prerequisite)
                report("reconnect_l2ping_host_tablet" + suffix, failed_prerequisite)
                break
            forward = report("reconnect_l2ping" + suffix, lambda: ping("tablet"))
            reverse = report("reconnect_l2ping_host_tablet" + suffix, lambda: ping("host"))
            if args.link_diagnostics:
                report("reconnect_link_diagnostics" + suffix, lambda: link_diagnostics("reconnect" + suffix))
            if any(r["status"] != "PASS" for r in (control, forward, reverse)):
                break  # Preserve the first failure; never reconnect to hide it.
    finally:
        for side, peer in peers.items():
            def restore(p=peer):
                value = p.call("cleanup")
                value["pass"] = bool(value["checks"]) and all(value["checks"].values()) and not value["errors"]
                return value
            report("restore_" + side, restore)
        for side, original in policy_restore.items():
            def restore_policy(s=side, old=original):
                command = privileged(s, ["hciconfig", args.adapter, "lp", ",".join(old).lower()])
                after = policy(s)
                return {"command": command, "before": old, "after": after,
                        "pass": command["rc"] == 0 and after == old}
            report("restore_link_policy_" + side, restore_policy)
        for side, original in mode_restore.items():
            def restore_mode(s=side, old=original):
                flags = [v for v in old if v != "PERIPHERAL"]
                command = privileged(s, ["hciconfig", args.adapter, "lm", ",".join(flags).lower() or "none"])
                after = privileged(s, ["hciconfig", args.adapter, "lm"])
                match = re.search(r"Link mode:\s*([^\n]*)", after["stdout"])
                return {"command": command, "after": after, "before": old,
                        "pass": command["rc"] == 0 and bool(match) and match[1].strip().split() == old}
            report("restore_link_mode_" + side, restore_mode)
        for peer in peers.values():
            peer.close()
        # Copy endpoint logs/data only to the caller's private output directory.
        with (out / "tablet.tar").open("wb") as f:
            subprocess.run(ssh + ["tar -C " + shlex.quote(remote_work) + " -cf - tablet"], stdout=f, check=True, timeout=30)
        if all(results.get("restore_" + side, {}).get("status") == "PASS" for side in peers):
            run(ssh + ["rm -rf -- " + shlex.quote(remote_work)])
        else:
            (out / "remote-recovery-path.txt").write_text(remote_work + "\n")
        for side in peers:
            # Capture kernel/controller errors without printing private addresses.
            (out / (side + "-kernel.txt")).write_text(privileged(side, ["dmesg", "--color=never"])["stdout"])
    return 0 if all(v["status"] == "PASS" for v in results.values()) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", help="SSH user@target (known host key required)")
    parser.add_argument("--serial", help="expected piano androidboot.serialno")
    parser.add_argument("--sudo-password-file", help="existing private tmpfs file; password is only passed through stdin")
    parser.add_argument("--output", help="new PRIVATE evidence directory; contains Bluetooth addresses")
    parser.add_argument("--adapter", default="hci0")
    parser.add_argument("--skip-obex", action="store_true", help="omit file transfer when investigating audio; no OBEX PASS is emitted")
    parser.add_argument("--reconnect-only", action="store_true", help="pair/connect and test bidirectional pings before/after reconnect; omit OBEX/audio")
    parser.add_argument("--reconnect-from", choices=("tablet", "host"), default="tablet", help="peer initiating the single reconnection")
    parser.add_argument("--reconnect-count", type=int, choices=(1, 2, 3), default=1, help="bounded intermittent-failure capture; stop at the first failed cycle")
    parser.add_argument("--reconnect-policy", choices=("default", "tablet-no-sniff", "tablet-no-role-switch", "host-no-sniff"), default="default", help="one-variable link control, applied while disconnected and restored at exit")
    parser.add_argument("--link-diagnostics", action="store_true", help="read link policy, supervision timeout and AFH after measured pings")
    parser.add_argument("--endpoint", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--obex-endpoint", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--work", help=argparse.SUPPRESS)
    parser.add_argument("--peer", help=argparse.SUPPRESS)
    a = parser.parse_args()
    if not re.fullmatch(r"hci[0-9]+", a.adapter):
        parser.error("invalid adapter name")
    if a.endpoint:
        endpoint(a)
    elif a.obex_endpoint:
        obex_endpoint(a)
    else:
        if not all((a.ssh, a.serial, a.output)):
            parser.error("--ssh, --serial and --output are required")
        sys.exit(main(a))
