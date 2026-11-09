# Image-building workflow

## Backend selection

| Target | Proposed backend | Constraints |
| --- | --- | --- |
| Ubuntu Server installation ISO | Official ISO + Subiquity Autoinstall / NoCloud | Preserve original boot modes; confirm ISO release-specific layout |
| Ubuntu cloud QCOW2 | Official cloud image + cloud-init, or Packer/QEMU | Validate cloud-init behavior and machine compatibility |
| Ubuntu Desktop live ISO | Cubic or a version-pinned live ISO remaster workflow | Release-specific boot and squashfs details |
| Ubuntu Core / supported preinstalled disk image | ubuntu-image and appropriate model/gadget definitions | Not a universal desktop/live-ISO builder |
| Armbian or custom ARM board IMG | Board-specific Armbian build and BSP/boot chain | Verify U-Boot, SoC, DTB, partition geometry, kernel and storage target |

## Mandatory build pipeline

1. Record OS release, source URL, license, architecture, SHA256 and expected boot model.
2. Verify downloaded upstream media against an **independently trusted** checksum or signature.
3. Record target artifact format and explicit backend selection.
4. Render a separate release-specific config; never reinterpret a generic profile as native autoinstall.
5. Use isolated temporary directories; never write to a physical disk as part of building an artifact.
6. Produce reproducibility metadata: input versions, checksum, build parameters, scripts and output hash.
7. Static checks: media partition tables, boot files, expected configuration and output checksum.
8. Dynamic checks: QEMU/VM boot, installer exit status, networking and post-install validation where supported.
9. Report unsupported architectures and any boot validation not performed.

## Autoinstall cautions

An autoinstall config can erase disks. Storage selection must never default to an arbitrary host disk. Require exact user-approved target disks for physical installation. Do not embed plaintext credentials or private keys in committed profiles. Prefer first-boot secret injection from an approved secure channel.

## ARM constraints

A valid ARM64 userspace does not imply a bootable device image. Board-specific firmware and DTB are required, and the build environment may need vendor-specific tools. Never copy DTB or U-Boot from another board solely because the CPU family matches.
