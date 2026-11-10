# Build the first A8 XNU kernel

The Windows workspace has no Xcode. WSL has produced v11 by applying a guarded
one-instruction patch to the v10 Mach-O; the full HakiOS build still exits with
post-link symbol-set/export-checker errors for donor IORPC exports. V11 reached
BSD initialization, then panicked at `pthread_shims.c:318` because the pthread
function table was null. The root cause is that the bundled Apple libpthread
provider was compiled only for the SWEET board. The A8 source-preparation
script now enables its provider sources and 56-byte storage layout for the
A5XELTE build. GitHub Actions run [42771897514](https://github.com/ACTUALLYGUNBILEG/GALAXY-A8-2018-HACKIOS/actions/runs/42771897514)
successfully built XNU 8796.141.3 and uploaded a kernel-only artifact. The
WSL-only diagnostic build disables `SWEET_HFS`; its donor integration expects
macOS target headers. Earlier boot milestones and their device results are in
the bring-up plan. The workflow at `.github/workflows/jackpotlte-xnu.yml`
uses a macOS 15 Intel runner and Xcode 16.4, pins the S8 donor and XNU build
helper, stages the known A5XELTE donor patch subset, then applies the local A8
overrides. The donor's GIC patch is trimmed only to omit its conflicting board
match; the A8 override script writes that match afterward.

The workflow builds a **kernel artifact only**. It does not package Samsung
BOOT, include an iOS root filesystem, or flash the phone. Its machine config is
still the A5XELTE donor config with A8 values overlaid, so a successful compile
is only the next diagnostic milestone, not proof the kernel will boot on the
A530N.

The workflow runs on pushes to `main` and supports **Actions → jackpotlte first
XNU build → Run workflow**. Run 42771897514 uploaded the artifact
`jackpotlte-xnu-kernel` (73,587,821 bytes, seven-day retention). The
`.gitignore` excludes the local BOOT readback, probe images, and generated ADT;
do not add those device images to a public source repository. Download the
artifact while signed in to GitHub and inspect its format and SHA-256 before
packaging it in a Samsung BOOT candidate.

This CI artifact is kernel-only. It has not been downloaded locally, wrapped
in the Samsung BOOT image, or tested on the A530N. Preserve the validated
header, DTBH, and ramdisk when preparing a candidate; inspect the full package
and keep the TWRP BOOT backup available before a BOOT-only test. Do not treat
the successful build as proof of a working boot or an iOS install image.

The runner choice follows GitHub's current runner images: macOS 14 was retired
on 2026-11-02, while the macOS 15 image includes Xcode 16.4. The S8 donor adds
the `IORPC.kernelContent` field needed by newer IIG output. [GitHub runner image
status](https://github.com/actions/runner-images), [XNU donor patch](https://github.com/Floppikrob/ios-galaxy-s8/blob/04b41729e89f702261e5599dbe3677e8ee5f5ee3/xnu/patches/0083-xcode27-iig-kernel-content.patch)
