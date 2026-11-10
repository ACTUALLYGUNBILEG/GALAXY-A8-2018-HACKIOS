# jackpotlte handoff probe

`probe.Image` is the device-specific handoff probe for the SM-A530N. It reads
arm64 CPU/system-register state, validates the FDT, and parses root RAM banks,
the FDT reservation map, and fixed `/reserved-memory` ranges. It writes the
measurements into the kernel-tree framebuffer handover region, requests one
DECON shadow update, and waits. It does not load XNU, access storage, or request
a reset. Exit requires a forced restart into recovery.

The address and display values are initial candidates from the public Korean
`jackpotlte_kor_07` Exynos 7885 kernel device tree. Confirm the live framebuffer
base, stride, panel mode, and DECON state before treating the overlay as proven.

## Build

With Zig 0.14.1 (the locally verified compiler):

```powershell
python tools/build_jackpot_probe.py --toolchain zig --zig C:\path\to\zig.exe
```

With an AArch64 GNU cross toolchain:

```sh
CROSS=aarch64-none-elf- shim/jackpotlte/build.sh
```

The output is `shim/jackpotlte/out/probe.Image`. A candidate was assembled at
`outputs/jackpotlte-probe-twrp-candidate.img` from the supplied Korean rev07
BOOT image. Inspect another private BOOT backup with
`python tools/a530n_boot.py info PATH`; create a separate candidate with
`python tools/a530n_boot.py pack STOCK probe.Image CANDIDATE`. If the stock BOOT
contains the recognized Samsung 256-byte OEM footer signature, explicitly pass
`--drop-oem-signature`; the rebuilt candidate is unsigned and needs an unlocked
boot chain that accepts custom images. The packer checks the configured board
name, DTBH chip ID, header format, and 32 MiB size limit. Confirm those values
against the exact installed firmware, device, and GPT. Make and verify a TWRP
BOOT backup before installing any candidate; this repository does not flash it.

Probe v2's separate candidate is `outputs/jackpotlte-probe-v2-rammap.img`. It
ran successfully and displayed three live RAM banks; the user returned to
TWRP. The third live bank is `0x880000000+0x80000000`, twice the size listed in
the packaged rev07 DTB.

Probe v3's separate candidate is
`outputs/jackpotlte-probe-v3-reservedmap.img`. It boot-looped on-device; do not
flash it again. The v3.1 candidate is
`outputs/jackpotlte-probe-v3.1-fdt-diagnostic.img`. It avoids the 130 KB
compiler-runtime expansion caused by a struct copy and draws a checkpoint
before parsing the live FDT. It completed the live FDT parse on-device and
displayed 11 reserved ranges. To generate the first single-core XNU entry tree,
run `python tools/mkadt_jackpotlte.py outputs/jackpotlte-entry.adt`. This needs
the S8 reference project's local `tools/adt.py` and `tools/mkadt.py` checkout
under `work/references/s8/`. The generated ADT is not a bootable kernel. The
first A8 source overrides are applied with `tools/apply_jackpotlte_xnu.py` to
the prepared A5XELTE-derived XNU tree. XNU 8796.141.3 has linked in the local
WSL environment, although the HakiOS post-link symbol-set/export checker still
exits with errors. The generator may report that the optional iPhone X
`/product` node is absent; that is expected for this kernel-only milestone.

## First XNU handoff candidate

`xnu_loader.Image` is a Samsung `ARMd`-style A8 loader. It expects EL1 with the
MMU off and a live FDT `/chosen/linux,initrd-start` and
`/chosen/linux,initrd-end` pair. The raw SWEETXNU v1 initrd payload contains the
linked Mach-O and entry ADT. The loader copies the kernel to the provisional
RAM2 window `0x880000000+0x20000000`, builds the XNU `boot_args`, and branches
to the kernel entry. It displays loader errors and halts; it does not write
storage or reboot to recovery.

Build the loader and raw payload with Zig and the local donor ADT helpers:

```powershell
python tools/build_jackpot_xnu_loader.py --toolchain zig --zig C:\path\to\zig.exe
python tools/mkpayload_jackpotlte.py outputs\jackpotlte-xnu-8796.141.3-development-arm64.mach outputs\jackpotlte-entry.adt outputs\jackpotlte-xnu-payload-v1.raw
```

The first offline candidate in
`outputs/jackpotlte-xnu-8796.141.3-entry-candidate.img` was flashed and
boot-looped at the Samsung logo. Offline symbol inspection found the loader
object importing `memset` and the linked ELF containing a large, unrelated
Zig compiler runtime. Candidate v2 avoids this import and reached the XNU
startup checkpoints through `arm_init_jump`; the Samsung splash remained
visible afterward. These five colored markers are emitted by the A5XELTE-based
XNU `start_first_cpu` path before and during MMU setup, FP enable, tunables,
and return to `arm_init`.

Candidate v3 is
`outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v3.img`. It zeroes the
provisional 512 MiB XNU RAM region using 64-bit stores before copying kernel
segments, explicitly selects SP_EL1, and installs loader exception vectors.
Its device photo reaches `HANDOFF TO XNU`, then stops before any XNU C-stage
text. The leading diagnosis is that the linked SWEET console still targets
the donor framebuffer at `0x67000000` even though the A530N board override
uses `0xEC000000`.

Candidate v4 is
`outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v4-fbfix.img`. It keeps the
v3 loader and patches the linked kernel console address to `0xEC000000` plus
the A8's 69 text rows. It passes offline BOOT-layout checks but is still an
untested diagnostic candidate. The S8 donor loader documents that stale
S-Boot RAM can hang XNU's early VM bootstrap. The XNU handoff, initrd FDT
properties, and high-RAM window are not yet stable. The user confirms a TWRP
BOOT backup was completed to microSD or USB OTG before candidate v1 was
flashed; it restores the previous experimental BOOT state, not stock Android.
The BOOT packer only creates an image file; it never flashes a device.
