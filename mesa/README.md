# Piano Mesa inputs

`source.json` pins upstream Mesa and the single `piano-fixes.patch` used by
both the desktop deb and the gpu-2404 builder. The patch contains the A830
revision-1 speedbin match and a shared-context publication fix. Contexts must
not enter the shared resource list until their state tracker is initialized;
failed creation leaves an empty list link for normal cleanup.

`shared-context-stress.c` uses real EGL/GLES calls: four threads create and
destroy shared contexts while a fifth allocates and deletes buffer storage.
Compile against EGL/GLES and pthreads, then select the candidate libraries:

```sh
LD_LIBRARY_PATH=/opt/piano/mesa-26.2.0/lib \
LIBGL_DRIVERS_PATH=/opt/piano/mesa-26.2.0/lib/dri \
  ./shared-context-stress Adreno
```

The renderer argument is mandatory. Do not disable threaded contexts for this
test. On the tested tablet, the original package crashed with SIGSEGV; the
fixed build completed 4,000 context lifetimes and over two million buffer
lifetimes. This is a concurrency regression, not complete GPU or suspend
coverage. A new process must load the updated libraries; an existing desktop
session retains its old mapped libraries until logout or reboot.

Build only the desktop package with `tools/build-device-debs.py --mesa-only
--mesa-build BUILD --output OUTPUT --version VERSION`. The builder validates
the source lock and every payload file. The snap provider must be rebuilt
separately; changing the desktop deb does not update an installed snap.

Remove the local shared-context change when the pinned upstream contains an
equivalent fix and the regression passes. No upstream submission is implied.
