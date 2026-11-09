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

## Image portability pipeline (initial working backend)

Once a target's evidence session is collected, select **virtual-machine**
or **physical-device**. The planner verifies every source evidence file hash
and separately checks a *locally supplied base image* against an independently
obtained SHA-256. It records observed target architecture, the operator-declared
source architecture, readiness gaps, and the intended output format.

```bash
# Generate plan for an existing verified base image and a VM target
python3 scripts/workflow/image_plan.py SESSION_DIRECTORY \
  --target virtual-machine --format qcow2 \
  --source /srv/images/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./image-plan.json

# The same plan can be created from a registered device
python3 scripts/workflow/manage.py image-plan lab-server SESSION_ID \
  --target virtual-machine --format qcow2 \
  --source /srv/images/base.img \
  --sha256 VERIFIED_64_HEX_SHA256 --source-arch amd64 \
  --output ./image-plan.json

# Once the plan reports build_allowed=true, perform OFFLINE conversion
# (requires qemu-img installed on the build host)
python3 scripts/workflow/build_image.py ./image-plan.json \
  --output ./output.qcow2
```

This generates an image and `output.qcow2.manifest.json`, including the
SHA-256 digest and virtual size. It **converts an already bootable source
image**; it does not automatically capture the running system, install
drivers, customize packages, reset machine identities, or make the output
bootable on arbitrary hardware. The created image requires a separate VM
boot test (machine type, firmware and virtual drivers) before deployment.

For `--target physical-device --format raw`, the planner returns explicit
blockers and **does not allow assembly** until a board-specific bootloader,
kernel/DTB or ACPI support, firmware, storage partition scheme and recovery
path are verified. A generic ARM64 system cannot be made universally
bootable merely by changing an image format.

Never pass block devices as input or output. The converter rejects paths
under `/dev`, `/proc` and `/sys`, output overwrites, unsupported
input formats, and images with a QEMU backing file. Keep source image
integrity metadata and licensing records. Source architecture is currently
an operator declaration and is **not** validated from guest filesystems;
this limitation is explicitly reported.

## Automatic Skill status bridge (optional)

The four image helpers now write a minimal progress checkpoint **only when
the user has opened a verified local preview**. The Agent need not invoke
`status.py` between every stage. A common session is linked by the
`discovery.session` field in the plan and the `discovery_session`
field in the build result.

`image-plan` reports trusted source hashing, evidence verification and the
compatibility decision. `image-build` reports source validation, format
inspection, conversion, verification and the output manifest. The
`first-boot` stage covers NoCloud files and optional ISO. `verify`
covers static image validation and optionally a QEMU smoke attempt.
Physical targets remain blocked; this change adds **observability, not new
physical-device image-building support**.

Use `python3 -m unittest discover -s tests -v` locally to validate the
stage integration; no CI is triggered by the Skill itself.
