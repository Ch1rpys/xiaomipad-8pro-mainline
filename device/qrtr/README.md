# QRTR discovery for the ADSP RAM probe

Use the unmodified upstream [linux-msm/qrtr](https://github.com/linux-msm/qrtr)
`qrtr-lookup` program to query Linux's existing nameservice. The source commit is
locked in `source.json`; the build uses upstream Meson targets and creates only a
static ARM64 lookup executable. It does not build or install a userspace daemon.

```sh
QRTR_SOURCE=/path/to/qrtr OUT_DIR=/path/to/separate-output \
    tools/build-qrtr-lookup.sh
```

Meson, Ninja, ccache and an ARM64 GNU cross compiler must be in PATH. The output
manifest records the compiler, static libc archive, source and executable hashes;
it is a local build receipt, not a complete release toolchain source lock.

The internal runner accepts this directory through `--qrtr-tool-dir` for the
ADSP NCM probe. With sufficient time remaining, it reuses the existing verified
file transfer and RAM cleanup, executes one lookup, and saves the raw table,
timestamps and exit status. The original candidate and its 60-second timer remain.

Upstream lookup sends NEW_LOOKUP to the local socket's QRTR control port. It reads
service advertisements; it does not send PMIC properties or application QMI RPCs.
The kernel already owns QRTR nameservice and PD mapping in this piano configuration, so no second
nameservice or PD mapper is installed.

An advertised service is not proof of RPC responsiveness or process-domain UP.
In particular, the local kernel PD mapper can advertise service 64; that is not
itself evidence of a remote ADSP service. Correlate node/port, remoteproc, RPMsg and
consumer logs before deciding what works. No timeout or empty table is relabeled
as a successful hardware check.

BSD-3-Clause attribution is in `NOTICE` and `LICENSES/qrtr-BSD-3-Clause.txt`.
The generated static executable also contains the compiler runtime; no prebuilt
executable is distributed here. An installed system should prefer its standard
qrtr-tools package.
