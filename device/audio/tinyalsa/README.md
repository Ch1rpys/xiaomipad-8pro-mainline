# Mixer inspection in the minimal RAM diagnostic

The small NCM root has no distribution ALSA utilities. Use the pinned, unmodified
[TinyALSA](https://github.com/tinyalsa/tinyalsa) `tinymix` to inspect actual ALSA
control names, enum choices and current values before choosing a capture route.
Ubuntu's installed audio stack continues to use distribution ALSA/UCM/PipeWire.

Build from a clean checkout of the commit in `source.json`:

```sh
TINYALSA_SOURCE=/path/to/tinyalsa OUT_DIR=/path/to/separate-output \
    tools/build-tinymix.sh
```

The wrapper uses the upstream Makefiles, an ARM64 GNU cross compiler and ccache.
Only the static library and `tinymix` target are built; Android plugin support is
not enabled. Output stays in the selected directory. `manifest.json` records the
source, compiler, static libc archive and executable hashes. This is a local
build receipt, not a complete release toolchain source lock.

The internal mic-probe runner's explicit `--mixer-tool-dir` option accepts this
output. After module loading succeeds and at least 20 seconds conservatively
remain, it serves one verified file on the existing piano NCM link, verifies its
hash again in RAM, and invokes only `tinymix -D CARD contents`.
The temporary executable is removed after collection; no boot image needs to be
rebuilt and no mixer value or recording mode is set. The executable itself also
supports setters, but the collector does not invoke them.

Download and control reads have separate short deadlines. Missing cards, transfer
failures and nonzero exits remain in the capture. A successful snapshot or command
exit does not prove every control value is valid, nor that a microphone records.
Real control reads, DSP routing and sound correlation still need piano testing.

The source is BSD-3-Clause; attribution and license are in `NOTICE` and `LICENSES`.
The generated static executable also contains the toolchain's C runtime; no
prebuilt executable is distributed here.
