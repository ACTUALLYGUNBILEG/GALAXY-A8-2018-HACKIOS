# SM-A530N bring-up plan

## Scope and confidence

Target only the **Samsung Galaxy A8 (2018), SM-A530N**. The upstream Linux board file is for the SM-A530F and uses the compatible strings `samsung,jackpotlte` and `samsung,exynos7885`. A public LineageOS device tree explicitly describes the SM-A530N as `jackpotlte`. This makes `jackpotlte` a good working codename, but does not prove that every F variant device-tree value applies to the Korean N variant.

The Korean `jackpotlte_kor_07` Samsung kernel device tree describes eight CPUs: six Cortex-A53 cores and two Cortex-A73 cores, exposed through PSCI. Its MPIDRs are `0x100`–`0x103`, `0x200`–`0x201`, `0x0`, and `0x1`; the probe records the booting core instead of assuming which one starts. The same source identifies eMMC, a 32 MiB BOOT image, an S6E3FA7 1080×2220 MIPI command-mode panel, DECON_F at `0x14860000`, and a 20 MiB framebuffer handover range at `0xEC000000`. Confirm these values against the live SM-A530N handoff before using them for XNU.

## Milestones

### 0. Build the handoff probe — live boot confirmed

- Build `shim/jackpotlte/probe.Image`, a freestanding AArch64 image that captures EL, SCTLR, MIDR, MPIDR, CPU feature registers, timer values, and the FDT pointer.
- Draw the captured values into the framebuffer handover region and request one DECON update using the Exynos 7885 register definitions.
- The probe was flashed and reached its diagnostic screen. It does not write storage or alter PMU reset state; it waits forever after drawing, so a forced restart is needed to leave it.
- The supplied BOOT image's rev07 DTB identifies the Korean JACKPOTLTE board and Exynos 7885. The 256-byte Samsung OEM signature was removed when creating the unsigned candidate. Its packed header, ramdisk, and DTBH were read back successfully.
- The live handoff values are recorded below. The run confirms a usable display path and the user has returned to TWRP after restarting. It does not confirm XNU execution or interrupt delivery.
- Probe v2 added a bounded parser for FDT RAM banks, ran on-device, and returned to TWRP. It reported three live banks; the third is twice the size listed in the packaged rev07 DTB.
- Probe v3 added FDT reservation-map and `/reserved-memory` parsing, but boot-looped on-device. The user can still enter TWRP. Withdraw v3 until the failure is diagnosed; return to v2 or restore the saved BOOT image first.
- Probe v3.1 replaces the struct copy that pulled in a 130 KB compiler-runtime expansion and adds a pre-parse framebuffer checkpoint. Its 18 KB image uses the same ramdisk and DTBH as v2; it has now completed FDT parsing on-device and displayed 11 reservation ranges.

### 1. Establish a device evidence bundle

- Record the exact model, Android build, bootloader version/state, and storage layout.
- Save and verify full partition backups before any write; keep them outside this repository.
- Capture the live device tree, boot image metadata, kernel command line, framebuffer handoff, and relevant Samsung kernel source release.
- Identify which A530N components differ from A530F (board revision, panel/touch, modem, partition map, boot-image format, and secure-boot policy).
- Keep serial numbers, EFS, calibration data, and other device-unique material private.

### 2. Complete the loader and recovery measurements

- The user reports TWRP 3.7.1_12 is available. BOOT is `/dev/block/mmcblk0p12`, 33,554,432 bytes. A read-only readback from an earlier session is saved at `outputs/jackpotlte-current-boot-twrp.img` with SHA-256 `3FA84CA087577CD0BE001F38694BEDCA6412B3AA1964B2BAD172FF3CCEC45E17`.
- The readback is an experimental BOOT state. The separately supplied `boot.img` has byte-identical ramdisk and DTBH data, while its kernel differs because the readback contains a probe. This strongly ties it to the installed BOOT, though the exact firmware build is unknown. The latest host ADB check found no attached device. The user confirms a TWRP BOOT backup was completed to microSD or USB OTG before the first XNU candidate; it restores the previous experimental state, not stock firmware.
- Compare the captured live reservation list with the packaged tree, then identify a persistent log route.
- BOOT size is confirmed at 32 MiB; the bootloader accepted and executed the unsigned probe. Formal unlock state still needs documentation.
- Do not invent partition numbers from the S8 or A5 projects.

### 3. Boot a single XNU core

- Start from a 4 KiB-capable arm64 XNU configuration, then add an A8-specific machine configuration.
- The initial ADT exists at `outputs/jackpotlte-entry.adt`; `tools/apply_jackpotlte_xnu.py` applies the first A8 overrides to the prepared A5XELTE-derived XNU tree. This remains donor-config plumbing, not a finished `jackpotlte` machine config.
- XNU 8796.141.3 links to a Mach-O kernel in the WSL environment, but HakiOS exits with post-link symbol-set/export checker errors. Candidate v1 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate.img` was flashed and boot-looped at the Samsung logo. Offline inspection found its unnecessary compiler-runtime import, a likely but unproven cause.
- Candidate v2 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v2.img` reached all five early XNU markers, including `arm_init_jump`, then stayed at the Samsung splash. Candidate v3 clears the provisional 512 MiB XNU window, explicitly selects SP_EL1, and adds loader exception reporting; its photo shows `HANDOFF TO XNU`, but no XNU C-stage output. Candidate v4 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v4-fbfix.img` passed the Samsung splash and stopped at a black screen with one fixed bright pixel. Source review found the A8 console disabled at stage 7 and the donor final-framebuffer map excluded by the `A5XELTE` guard.
- Candidate v5 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v5-persistent-fb.img` contains aliases for the 20 MiB framebuffer and DECON window through final TTBR1. On-device it reached stage 7 and panicked at `arm_vm_init.c:1857`: the chosen alias lies below `gVirtBase`, so the root L1 entry had not been created by the existing `init_ptpages(gVirtBase, ...)` call.
- Candidate v6 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v6-l1-fb.img` calls `init_ptpages` for the alias's L1 span before validating/filling its L2 entries. The user reports that it reached XNU stage 20, `kprintf startup complete`, confirming early VM setup and console initialization. This is a kernel milestone, not a completed startup or iOS boot.
- Candidate v7 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v7-bootstrap-diag.img` reached stage 33 (`kernel_bootstrap entered`); the user's photo shows stages 20–33 and no panic text.
- Candidate v8 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v8-bootstrap-vm-diag.img` is 15,398,928 bytes with SHA-256 `6125C43515FA5E2CE08FEB00FEFA65FEE52F2C85CF52994F5353D1A449D7F90F`. It adds markers around page-bucket allocation, `pmap_startup`, and VM bootstrap return; later markers continue through stage 70. Package inspection confirms a valid A530N DTBH and a size below the 32 MiB BOOT partition limit. The file is copied to `F:\jackpotlte-xnu-v8-bootstrap-vm-diag.img`.
- The latest v8 photo shows stage 42, `vm page bucket locks initialized`. The next operation is `pmap_startup`; the photo alone does not show whether the phone is still working or has stalled.
- Candidate v9 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v9-bootstrap-pmap-diag.img` is 15,398,928 bytes with SHA-256 `DDD5103DDAEF6DE44461D08751284840EFC336CBAA3E7DDC38B45A2D9A5404B2`. It inserts stages 43–54 around page sizing, vm_pages allocation, frame initialization, free-list release, and pmap return, then shifts later VM/startup markers through stage 82. Package inspection confirms five Exynos 7885 DTBH entries and the 32 MiB BOOT limit. It is copied to `F:\jackpotlte-xnu-v9-bootstrap-pmap-diag.img`.
- The v9 Mach-O contains the new markers. The WSL build log still reports HakiOS's donor IORPC export-check errors after linking; the diagnostic build also disables `SWEET_HFS` because the donor integration expects macOS target headers. V9 remains a kernel diagnostic, not a usable filesystem or iOS install.
- The v9 on-device photos show stages 68–79, then `Kernel data abort` at PC `0xfffffff0078f86c4` with FAR `0x28`. Symbolication maps the PC to `SHA1Init`, called from `IOPlatformExpertDevice::generatePlatformUUID` during IOKit startup. The SHA-1 wrapper reads `g_crypto_funcs->ccsha1_di` at offset `0x28`; the diagnostic kernel has no crypto provider registered at this point, so that table is null.
- Candidate v10 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v10-crypto-uuid-guard.img` guards the optional UUID derivation on `crypto_init`. It is 15,398,928 bytes with SHA-256 `9AC86C6A9F420BD913E1CB9A33A90021393B041F6C2597BE23F00946948918E8`, passes offline BOOT/DTBH/partition-size inspection, and is copied to `F:\jackpotlte-xnu-v10-crypto-uuid-guard.img`. Its build emitted a Mach-O, but the WSL wrapper still exits on the donor IORPC export checks. On-device it passed the earlier UUID panic and reached stage 82 before a CPU 0 startup timeout.

- The user tested v10 and the latest photo shows stages 68–82 followed by `SWEET CPU: cpu=0 startup timeout (reset/MMU/GIC/SGI1)` at `SweetCPU.cpp:166`. This is a CPU bring-up failure, after VM startup and IOKit had progressed beyond the previous UUID panic.
- Candidate v11 at `outputs/jackpotlte-xnu-8796.141.3-entry-candidate-v11-singlecore-signal-bootstrap.img` is 15,398,928 bytes with SHA-256 `1520DA3B38FF78C9806E42CAF4E7A3058C1F72E2638C201E8275C5BB03EC2260`. It preserves the validated A530N DTBH and loader, with a single-core CPU-signal initialization diagnostic. The intended source change in `work/xnu-8796.141.3/iokit/Kernel/arm/SweetCPU.cpp` calls XNU's `cpu_signal_handler()` locally for the already-running boot CPU, avoiding an early SGI before interrupt initialization. Since the current Windows/WSL environment has no Apple Xcode linker or SDK, the artifact was produced by a guarded one-instruction patch to the v10 Mach-O; it is not a clean rebuild. `tools/patch_v10_bootcpu_signal.py` verifies the exact input hash and expected instruction before patching. This workaround does not prove GIC SGI delivery, and v11 is an experimental BOOT diagnostic, not an iOS install image.
- The v11 package passes offline inspection: five Exynos 7885 DTBH entries, 2,048-byte page size, preserved 37,440-byte Samsung loader image, 14,474,800-byte ramdisk, 16-byte `SEANDROIDENFORCE` marker, and total image size below the 32 MiB BOOT limit.
- The user tested v11. Its photo shows XNU reaching BSD initialization and panicking at `pthread_shims.c:318`: `pthread kernel extension not loaded (function table is NULL)`. Source inspection found the built-in Apple libpthread provider is present but its provider sources are gated by `ARM64_BOARD_CONFIG_SWEET`, leaving the table null in the A5XELTE-configured build. `tools/apply_jackpotlte_xnu.py` now enables the provider, its BSD header include paths, and the matching 56-byte `ksyn_waitq_element` layout in the CI-prepared source. This is not yet rebuilt: the local Windows/WSL environment lacks Apple's Xcode linker and SDK, no Apple SDK copy is present in the searched Downloads/Documents/F: folders, and no v12 image exists.

The candidates preserve the v4 loader and its validated A530N DTBH, remove the Samsung OEM signature, and assume a live FDT `linux,initrd-start/end` range plus the provisional `0x880000000+0x20000000` XNU RAM window. Do not treat them as known-good install or recovery images. Candidate v11 is the current BOOT-only diagnostic and panics because the pthread provider is unregistered. Rebuild a v12 source candidate before another flash; do not wipe data or write other partitions. The user confirmed a TWRP BOOT backup exists on removable storage.
- Bring up exception vectors, memory regions, early allocator, serial/framebuffer diagnostics, GIC interrupt delivery, and the physical/architected timer.
- Boot only the primary core first. Test the provisional high-RAM window before allocator use; do not assume the lower banks or all 2 GiB of RAM2 are free.
- Keep logging persistent so panics can be collected after returning to recovery.

### 4. Add CPU and basic I/O support

- Bring up secondary Cortex-A53 and Cortex-A73 cores through the boot firmware's PSCI path, validating cluster power and coherency separately.
- Probe storage and partition mapping from device evidence; choose a read-only diagnostic root before considering a writable filesystem.
- Identify the panel controller, display engine, touch controller, regulators, and GPIOs from the exact A530N device tree and kernel sources.
- Present a basic framebuffer and input events before attempting iOS userland.

### 5. Reach an iOS diagnostic shell, then GUI

- Only after stable XNU boot and storage access, adapt the userland/root-image workflow from the references.
- Use user-supplied Apple firmware; do not check IPSW contents, extracted system images, or proprietary binaries into the repository.
- Start with launchd and diagnostics. Add display services, backboardd, and SpringBoard incrementally, recording logs and known failures.
- Track security stubs, unavailable services, and nonfunctional hardware plainly. A booting UI is not evidence of a secure or daily-usable phone.

## Reference reuse map

| Reference | Useful for | Must be re-derived for SM-A530N |
| --- | --- | --- |
| [ios-galaxy-s8](https://github.com/Floppikrob/ios-galaxy-s8) | Samsung S-Boot loader shape, XNU patch/build workflow, Apple Device Tree generation, persistent logging, Exynos debugging methods | Exynos 8895 MMIO, memory map, CPU startup, GIC/timer wiring, UFS, display/touch drivers, partition numbers |
| [ios-a5xelte `herolte` branch](https://github.com/wardevsa/ios-a5xelte/tree/herolte) | Stage-0 handoff probe and Samsung BOOT image packaging flow; its board is Galaxy S7 / Exynos 8890 | Exynos 8890 MMIO, memory map, CPU startup, display/touch drivers, partition numbers |
| [A5XELTE base](https://github.com/orhunnx/ios-a5xelte) | 4 KiB XNU lineage, Samsung boot packaging, evidence discipline | Exynos 7580 peripheral map, CPU topology, clocks, display/touch implementation, install layout |
| [Linux Exynos 7885 DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/exynos/exynos7885.dtsi) | Public SoC topology and initial generic node descriptions | Samsung firmware behavior and gaps not represented in upstream Linux DTS |
| [Linux `jackpotlte` DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/exynos/exynos7885-jackpotlte.dts) | Initial A8 board-level node references | File is identified as SM-A530F; compare every value with the SM-A530N captures |
| [SM-A530N LineageOS tree](https://github.com/MacBookPro34-comma-7/android_device_samsung_jackpotlte) | Confirms a public device tree targeting SM-A530N and points to common 7885 kernel/device sources | Android device-tree settings are not a ready-made XNU platform description |

## iOS 16 target and port choice

The intended system is the experimental **iOS 16.7.16 (20H392) iPhone X userland** over an **XNU 8796** kernel adapted for the SM-A530N. The cited Galaxy S7 and S8 projects report this XNU/userland combination booting on real Samsung Exynos phones, so the project target is feasible in principle. Their status reports are project evidence, not proof that their images work on the A8.

| Source | Reuse for this port | Must be replaced or checked |
| --- | --- | --- |
| [`ios-a5xelte` `herolte` branch](https://github.com/wardevsa/ios-a5xelte/tree/herolte) | Primary process reference: Samsung S-Boot loader in BOOT, XNU 8796 setup, diagnostics, and the underlying A5XELTE Exynos/eMMC bring-up | `herolte` is Exynos 8890 and uses UFS; the embedded A5XELTE path is Exynos 7580. Neither is Exynos 7885 |
| [`ios-galaxy-s8`](https://github.com/Floppikrob/ios-galaxy-s8) | Samsung S-Boot → loader → XNU handoff, iPhone X iOS 16.7.16 userland, recovery-based logging, 4 KiB XNU setup | Exynos 8895 SoC, CPU/PMU startup, memory/carve-outs, UFS, touch and panel are different |
| [`ios-v60`](https://github.com/ch1tmdgus/ios-v60) | Recent example of carrying an iOS 16/XNU port to another board and validating GUI/touch on hardware | Snapdragon 865; little A8 hardware code transfers |
| [`pixelios-kernel`](https://github.com/PixOS-Project/pixelios-kernel) | Clear shared-kernel / SoC / device-tree structure, memory captures, and staged hardware gates | Tensor G1 with fastboot, UFS, and Pixel boot flow; not an A8 donor |
| [`hackiosx.dev`](https://hackiosx.dev/) | Porting sequence, source map, and examples of real iOS userland running on Android hardware | HackiOS's UEFI path targets a Snapdragon 778G device; use its Samsung-specific guidance only where applicable |

The most transferable combination is therefore the Samsung Exynos loader/XNU work from `herolte`/S8, the eMMC lessons from A5XELTE, and a new `jackpotlte` device layer. The live v2 probe proved that S-Boot executes our image and preserves the display handoff. Probe v3 boot-looped. Probe v3.1 has now completed FDT parsing on-device and captured 11 live reservation ranges. The iOS root filesystem and its licensing/security work come only after single-core XNU, memory ownership, interrupts/timer, storage, display, and touch are understood.

## Hardware evidence ledger

| Item | Current value | Evidence / next check |
| --- | --- | --- |
| Target model | SM-A530N | User-provided target; confirm on device download mode and system properties |
| Working codename | `jackpotlte` | SM-A530N community device tree; verify live device identity |
| SoC family | Exynos 7885 | Upstream A8 board description; verify exact Korean variant |
| CPU topology | 6× Cortex-A53 + 2× Cortex-A73 in upstream DTS | Capture live DT/firmware data; verify MPIDRs, boot core, cluster power/coherency |
| RAM banks | Live v2 reports `0x80000000+0x3DA00000`, `0xC0000000+0x40000000`, and `0x880000000+0x80000000` | Live screenshot; packaged rev07 DTB lists only `0x40000000` for the third bank. Use the live values provisionally and capture live reservations before XNU allocation |
| Reserved memory | v3.1 displayed 11 live ranges; the full list is below. All end at or below `0x100000000`; none overlaps RAM2 at `0x880000000+0x80000000` | User photo of live FDT parser; compare with the packaged DTB before XNU allocator use |
| Probe image address | v1 `0x40134000`; v2 `0x80148000`; v3.1 `0x800F4000` | User-photo observations. v1 is outside the live banks; v2/v3.1 are inside live RAM0. Treat load placement as variable |
| Page granule supported by boot firmware / XNU config | Live `ID_AA64MMFR0_EL1=0x1122`; TGran4 field is 0 (4 KiB supported) | Use a 4 KiB XNU page configuration; validate XNU translation setup |
| GIC and timer routing | Exynos 7885 DTS: GICD `0x12301000`, GICC `0x12302000`; `CNTFRQ_EL0=0x18CBA80` (26 MHz). Mainline DTS says virtual timer PPI 11 is not wired; physical timer PPI 14 / INTID 30 is the initial candidate | Probe only read the counter. GIC mapping and interrupt delivery remain untested on this phone |
| Storage type/controller | eMMC via Exynos DW-MMC at `0x13500000` in Korean kernel tree | Verify on device and against stock image |
| BOOT partition | `/dev/block/mmcblk0p12`, 33,554,432 bytes (32 MiB) | Read from live TWRP; Samsung BOOT image packaging must respect this limit |
| Display engine | DECON_F baseline `0x14860000`; live trigger register before update was `0x1290` | Probe rendered on screen after requesting the shadow update; exact panel timing still needs validation |
| Panel and resolution | S6E3FA7, 1080×2220 in the Korean kernel DTS | Confirm panel revision and live scanout mode |
| Framebuffer handover | Probe rendered through candidate base `0xEC000000` using 1080×2220×4 stride | Visible overlay confirms this write/scanout path; verify format and full buffer extent before adding graphics |
| Touch controller and rail sequence | Unknown for this target | Identify from A530N DT/kernel and verify with input probes |
| Bootloader unlock and temporary boot options | Unsigned probe candidate loaded from BOOT and executed; TWRP is available | Current chain accepts this candidate; record formal unlock state and whether any temporary path exists |
| Recovery path | TWRP 3.7.1_12 is live; ADB reports product `twrp_jackpotlte` | TWRP remains available. Current BOOT readback is saved locally, but is experimental; stock restore has not been verified |

## Initial exit criteria

The diagnostic boot, live RAM-map, and reservation-parse milestones are complete: v1, v2, and v3.1 reached their screens. XNU candidate v4 passed the Samsung splash, then reached a black screen with one fixed bright pixel. V5 reached stages 1–7 and panicked when `sweet_early_map_final` found no valid table descriptor at the alias VA's L1 index. V6 fixed the L1 table issue and reached stage 20; v7 reached stage 33; v8 reached stage 42; and v9 passed stage 79 before an IOKit platform-UUID SHA-1 panic. V10 skipped that optional calculation and reached stage 82 before the CPU 0 startup timeout. V11 passed the timeout but panicked during BSD initialization because the pthread provider's function table remained null. The A5XELTE provider guard fix is now in the source preparation script; v12 needs a clean Xcode build before another device trial. The user reports TWRP remains available and has a saved BOOT backup. Probe v3 boot-looped and must not be flashed again. A verified stock restore, GIC interrupt delivery, and allocator-safe memory ownership remain unresolved.

## Live probe observations

Values transcribed from the user's device photos of the diagnostic screen:

| Field | Observed value | Interpretation |
| --- | --- | --- |
| CurrentEL | `1` | S-Boot entered the probe at EL1 |
| SCTLR_EL1 | `0x30C5183E` | MMU enable bit is clear; instruction and data cache enable bits are set |
| MIDR_EL1 | `0x410FD034` | ARM Cortex-A53, revision r0p4 |
| MPIDR_EL1 | `0x80000100` | Affinity fields identify A53 cluster 1, core 0 (`0x100`) |
| ID_AA64MMFR0_EL1 | `0x1122` | TGran4 field is 0; 4 KiB granule supported |
| ID_AA64PFR0_EL1 | `0x2222` | Captured as baseline CPU feature data |
| ID_AA64ISAR0_EL1 | `0x11120` | Captured as baseline CPU feature data |
| CNTFRQ_EL0 | `0x18CBA80` | 26 MHz architected counter frequency |
| FDT | `0x8A000000`, valid, size `0x2B200` | Live firmware device tree is present at the handoff register |
| Live RAM0 | `0x80000000+0x3DA00000` | v2/v3.1 FDT parser; bank begins at 2 GiB and is just under 1 GiB long |
| Live RAM1 | `0xC0000000+0x40000000` | v2/v3.1 FDT parser; 1 GiB bank |
| Live RAM2 | `0x880000000+0x80000000` | v2/v3.1 FDT parser; 2 GiB bank, twice the static rev07 value |
| Probe image address | v1 `0x40134000`; v2 `0x80148000`; v3.1 `0x800F4000` | Runtime addresses reported at each image entry; v2/v3.1 lie in live RAM0 |
| Live reserved ranges | 11 entries below | v3.1 parsed FDT reserve-map and `/reserved-memory`; photo shows `RSV COUNT: 0xB` |
| Framebuffer | `0xEC000000` | Probe overlay is visible using this candidate framebuffer base |
| DECON trigger register | v2 `0x1290` before its update; v3.1 `0x1281` after the earlier pre-parse display flush | The reads occur at different points in the display sequence; do not treat them as contradictory |
| Recovery | TWRP reached after v1/v2 runs; v3.1 currently waits on its diagnostic screen | Restart to TWRP before another flash |

The diagnostic screen proves the image was loaded and executed, the FDT parser
completed, and the framebuffer/DECON update path works well enough to show
text. The 11 ranges shown by v3.1 are:

| FDT range | Base + size | Notes |
| --- | --- | --- |
| FDT reserve-map | `0xE0000000+0x00D00000` | Ends at `0xE0D00000` |
| Framebuffer | `0xEC000000+0x01400000` | Matches the Korean rev07 tree |
| DRAM test | `0x80002000+0x2000` | Low RAM0 carve-out |
| Modem interface | `0xF5400000+0x08800000` | Ends at `0xFDC00000` |
| CP RAM logging | `0xFDC00000+0x02000000` | Ends at `0xFFC00000` |
| GNSS interface | `0xFFC00000+0x00400000` | Ends at 4 GiB |
| Secure debug | `0x80000000+0x1000` | Low RAM0 carve-out |
| TIMA | `0xB8000000+0x00200000` | Within RAM0 |
| Secure log | `0xC0000000+0x80000` | At RAM1 base |
| Wi-Fi/BT interface | `0xE9000000+0x00400000` | Ends at `0xE9400000` |
| ABOX reserved memory | `0xE9400000+0x00400000` | Ends at `0xE9800000` |

No listed range overlaps live RAM2 at `0x880000000+0x80000000`. A conservative
first XNU experiment can reserve only the first 512 MiB of that bank
(`0x880000000+0x20000000`) for a single-core allocator, leaving the rest unused.
This is a candidate layout, not proof the bank is physically safe or directly
addressable by this XNU configuration; verify address-width handling and add an
early read/write memory test before general allocation. The probe does not
initialize GIC interrupts, program a timer interrupt, test secondary CPUs, read
storage, enter XNU, or implement an automatic reboot to recovery.
