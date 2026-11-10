# XNU 8796 port map for `jackpotlte`

This is the working hardware map for the first A530N-specific XNU build. The target is XNU 8796 with the iPhone X iOS 16.7.16 userland used by the Samsung S7/S8 ports. The first kernel milestone is a single-core diagnostic boot; it is not an install image.

## Confirmed on this SM-A530N

| Item | Evidence | Port use |
| --- | --- | --- |
| Boot handoff | Probe v2 and v3.1 ran from Samsung BOOT; earlier probe runs returned to TWRP | Keep the Samsung BOOT loader chain and TWRP recovery path |
| Boot CPU | `MIDR_EL1=0x410FD034`, `MPIDR_EL1=0x80000100` | Start with the Cortex-A53 at MPIDR `0x100`; keep `cpus=1` |
| Page size | `ID_AA64MMFR0_EL1=0x1122` | Configure XNU for 4 KiB pages; do not enable 16 KiB pages |
| Counter | `CNTFRQ_EL0=0x18CBA80` | 26 MHz counter; timer interrupt delivery still needs a kernel test |
| Live RAM | FDT v3.1: `0x80000000+0x3DA00000`, `0xC0000000+0x40000000`, `0x880000000+0x80000000` | Live FDT is authoritative over the smaller static third-bank size; high bank is a candidate only after XNU address-width and memory-test checks |
| Live reservations | FDT v3.1 parsed 11 entries, all below or ending at 4 GiB | Full list below; no listed carve-out intersects RAM2, but this does not prove that RAM2 is safe/usable |
| Probe image | v3.1 reported `0x800F4000` | Variable placement in low RAM; exclude the loaded image and handoff structures from any allocator |
| Scanout | Text appeared at framebuffer `0xEC000000`; 1080×2220, 32-bit pixels from the Korean board tree; v3.1 DECON trigger read `0x1281` after its pre-parse flush | Preserve the bootloader framebuffer for early XNU logs; v2's `0x1290` was read before that flush and is not a comparable measurement |
| Recovery and BOOT partition | TWRP 3.7.1_12 is live; `/dev/block/mmcblk0p12` is 33,554,432 bytes | Current partition readback is `outputs/jackpotlte-current-boot-twrp.img`; it preserves the experimental state, not a stock restore |

### Live FDT reservation list

Probe v3.1 displayed `RSV COUNT: 0xB` and completed parsing at FDT address
`0x8A000000` (size `0x2B200`). These values are transcribed from the user's
device photo:

| Range | Base + size |
| --- | --- |
| FDT reserve-map | `0xE0000000+0x00D00000` |
| Framebuffer | `0xEC000000+0x01400000` |
| DRAM test | `0x80002000+0x2000` |
| Modem interface | `0xF5400000+0x08800000` |
| CP RAM logging | `0xFDC00000+0x02000000` |
| GNSS interface | `0xFFC00000+0x00400000` |
| Secure debug | `0x80000000+0x1000` |
| TIMA | `0xB8000000+0x00200000` |
| Secure log | `0xC0000000+0x80000` |
| Wi-Fi/BT interface | `0xE9000000+0x00400000` |
| ABOX reserved memory | `0xE9400000+0x00400000` |

The existing live FDT parser treats the first range as a reservation. Compare
it against the structure's address/size semantics and the packaged DTB before
using any of these values to reclaim memory. A provisional XNU test window is
`0x880000000+0x20000000` (the first 512 MiB of RAM2); leave the remaining 1.5
GiB unused. The CPU advertises 40-bit physical-address support via the captured
`ID_AA64MMFR0_EL1=0x1122`, but XNU's own physical-address limit and page-table
mapping still need to be checked. First access this window with a bounded
memory test, then add it to a general allocator only after logs show no aborts
or aliasing.

## A8-specific source values that still need a device-level check

The Exynos 7885 tree describes a GIC-400 with distributor at `0x12301000` and CPU interface at `0x12302000`. Its generic timer is 26 MHz. Mainline DTS explicitly comments that the hypervisor virtual timer is not wired to GIC; use the non-secure physical timer PPI 14 (INTID 30) as the first XNU timer candidate, not virtual-timer INTID 27. The v2 probe measured the counter frequency but did not configure or receive an interrupt, so timer delivery still needs a device boot. [Exynos 7885 Linux DTS](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/exynos/exynos7885.dtsi)

The same tree describes embedded eMMC through Samsung's DesignWare MMC controller at `0x13500000` (with a command-queue window at `0x13508000`). Mainline Linux's Exynos78xx variant documents a 64-bit FIFO accessed as two 32-bit register reads; carry that as a driver lead and confirm it against the exact A530N controller setup. The A5XELTE work has a read-only GPT probe and later a disk-root path, but its controller is at `0x13540000`; those register addresses and clock setup cannot be copied to this phone. Do not add the A5 driver's write/root path until the A530N controller has passed a read-only sector/GPT check. [Linux DW-MSHC note](https://lkml.iu.edu/2303.1/05886.html)

## Donor code strategy

| Donor piece | Reuse | A530N change |
| --- | --- | --- |
| XNU 8796 base and shared SWEET patches | Build fixes, 4 KiB entry, early console, A53-safe code generation, single-core platform plumbing | Add a distinct `jackpotlte` board identity and validate each patch against the selected XNU 8796 source |
| `herolte` / A5XELTE | Samsung BOOT packaging, 4 KiB XNU startup, GICv2 shape, read-only eMMC investigation | Replace Exynos 8890/7580 addresses, CPU topology, memory map, panel and storage setup |
| Galaxy S8 / `dreamlte` | Working loader-to-XNU `boot_args` handoff and iPhone X 16.7.16 root workflow | Replace Exynos 8895/UFS, high-RAM assumptions, GIC/timer values, display and touch setup |
| V60 and Pixel 6a projects | Cross-board port workflow and staged validation | Hardware drivers do not transfer to Exynos 7885 |

The build target should initially use the donor's plain `arm64` / ARMv8-A toolchain settings that avoid LSE instructions on the A53. The A530N contains six A53 and two A73 cores, but only the observed A53 boot core belongs in the first Apple Device Tree. PSCI and the big cluster remain out of the first milestone.

## Next gate

1. The user confirms a TWRP BOOT backup was completed to microSD or USB OTG before candidate v1 was flashed. TWRP remains accessible after the bootloop. The backup restores the earlier experimental BOOT state, not stock Android. The separately supplied `boot.img` has byte-identical ramdisk and DTBH data to the earlier partition readback, but the exact firmware build is unknown.
2. Candidate v1 boot-looped at the Samsung logo. Candidate v2 reached all five XNU startup markers through `arm_init_jump`; v3 showed `HANDOFF TO XNU`; v4 stopped after the splash with a black screen and one pixel. Candidate v5 reached stage 7, then panicked because the framebuffer alias had no L1 table. V6 added the parent table and reached stage 20. V7 reached stage 33 (`kernel_bootstrap entered`); the latest photo shows no panic text.
3. Candidate v8 reached stage 42, `vm page bucket locks initialized`. Candidate v9 keeps the v4 loader, validated A530N DTBH, and v6 framebuffer mapping, and adds checkpoints through `pmap_startup` (stages 43–54). Later markers continue through stage 82. Its Mach-O links, although the HakiOS post-link IORPC export checker still reports donor errors. The first ADT and A8 override values still use an A5XELTE-derived tree, not a standalone `jackpotlte` machine configuration.
4. V11 passed the earlier CPU-startup timeout and panicked in BSD initialization at `pthread_shims.c:318` because the pthread function table was null. The source preparation script now enables the built-in A5XELTE libpthread provider with its matching 56-byte kernel storage layout. GitHub Actions run [42771897514](https://github.com/ACTUALLYGUNBILEG/GALAXY-A8-2018-HACKIOS/actions/runs/42771897514) successfully built XNU and uploaded the kernel-only artifact. Download and inspect it, create and inspect a Samsung BOOT package, then test BOOT only from TWRP without wiping other partitions. The user confirms a TWRP BOOT backup is available on removable storage. Recovery, safe RAM ownership, interrupts, and timer delivery remain unproven.

The cited S8 project reports the full XNU 8796/iOS 16.7.16 path on its own Exynos 8895 hardware. That establishes a useful donor, not compatibility of its kernel image with the A530N. [S8 source](https://github.com/Floppikrob/ios-galaxy-s8) · [A5XELTE `herolte` source](https://github.com/wardevsa/ios-a5xelte/tree/herolte)
