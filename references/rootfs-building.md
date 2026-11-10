# Portable RootFS Builder — Skill operation contract

The AI Agent owns this workflow. The helper is a **VM-only, offline, allowlisted
RootFS customization backend**, not a generic device flasher or web product.
It is opt-in for artifact writes and does not install packages or run
user-provided code.

## Preconditions

- A collected and SHA-256 verified device session, plus an image-plan.json
  with all mandatory guest/partition/boot checks passing.
- The source image is an existing, shut-down Linux VM disk, RAW or QCOW2,
  with a trusted SHA-256, matching guest architecture, and no backing chain.
- The build host has qemu-img, virt-cat, virt-customize, virt-sysprep,
  virt-inspector, virt-filesystems, virt-drivers and guestfish. If a NoCloud
  seed ISO is requested, also provide genisoimage or mkisofs.
- The source guest has cloud-init configuration at /etc/cloud/cloud.cfg.
  This check is **not** proof that NoCloud will run at first boot.
- Exact target class: virtual-machine. Physical hardware IMG, BSP, DTB,
  vendor bootloader, flash medium and recovery remain separately blocked.

No automatic package installation, privilege escalation or network access
is permitted. Do not operate on an image being written by a live guest.

## Strict declarative recipe

Start from profiles/examples/rootfs-config.json and substitute an absolute
path to a real **public** SSH key, a unique instance ID, and a valid hostname.

~~~json
{
  "schema_version": 1,
  "hostname": "portable-guest",
  "motd": "Managed by Ubuntu Customizer\n",
  "first_boot": {
    "mode": "nocloud",
    "username": "ubuntu",
    "instance_id": "new-instance-001",
    "ssh_public_key": "/home/user/.ssh/id_ed25519.pub",
    "seed_iso": false
  }
}
~~~

Additional keys, private keys, root login, shell snippets, arbitrary guest
paths, usernames with metacharacters and oversized MOTDs are rejected.
If first_boot.seed_iso=true, an optional cidata ISO is created; otherwise
user-data and meta-data files are generated for an approved NoCloud source.

## Agent-guided operations

1. Present a concise summary of image-plan compatibility, source checksum,
   expected output format, exact local modifications and remaining unknowns.
2. Execute a **read-only planning step**; it checks image-plan provenance,
   input bytes, user recipe and dependencies. No disk output is created:

~~~bash
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json --dry-run
~~~

3. Ask for *separate explicit authorization* to create a new local bundle.
   Image build approval is **not** permission to flash or install on hardware.
4. Only when approved, execute:

~~~bash
python3 scripts/workflow/rootfs_builder.py image-plan.json \
  --config rootfs-config.json \
  --output-dir ./rootfs-bundle-001 --approved
~~~

5. Read the output summary and verify the bundle again:

~~~bash
python3 scripts/workflow/rootfs_builder.py \
  --verify-bundle ./rootfs-bundle-001
~~~

The output directory must be **new** and has this shape:

~~~text
rootfs-bundle-001/
├── image.qcow2                  # or image.img for RAW target format
├── build-manifest.json          # source+recipe+plan+output checksums
├── build-config.json            # sanitized declarative recipe; no local key path
└── seed/
    ├── user-data
    ├── meta-data
    └── manifest.json
# Optional: seed.iso (NoCloud cidata)
~~~

## Safe build pipeline

- Revalidate original image-plan and SHA-256; run guest inspection again.
- Convert original source image into a **private RAW working copy**.
- Fail if original source checksum changes during staging or cloud-init
  configuration is unavailable in the cloned guest.
- On this working copy ONLY, use virt-customize --no-network to set hostname
  and a root-owned, world-readable /etc/motd.
- On this working copy ONLY, run virt-sysprep with exactly the
  machine-id,ssh-hostkeys operations. No defaults/all operations.
- Generate the NoCloud seed from the public SSH key, no passwords.
- Convert the working image to the requested RAW/QCOW2 format.
- Reinspect image partition scheme, Linux guest architecture/distro,
  kernel and boot information; compare against original plan evidence.
  Read back /etc/hostname and /etc/motd to verify customization.
- SHA-256 the image, sanitized build configuration and seed; record the
  exact image-plan digest, then write build-manifest.json in a private
  newly created output directory. Verify the bundle and only then publish
  a complete result. Remove temporary staging and newly created partial
  output on failure. Never overwrite an existing bundle.
- A verified manifest is proof of **artifact integrity only**, not guest
  bootability, full identity scrubbing, an applied cloud-init configuration,
  hardware driver support or remote login availability.

## Security and limits

- No host block-device writes and no flash operations. Script arguments
  are fixed argv arrays, never a shell or user-controlled command program.
- Libguestfs guest network is disabled; all mutations target private scratch.
- Version 1 limits source virtual disk size to 64 GiB and its fixed recipe
  fields. It does NOT install packages, activate services, enable dynamic
  kernel modules, modify bootloaders, install a distribution, or build a
  physical-board IMG.
- The original image source SHA-256 must remain unchanged. Keep the source
  and guest offline throughout processing.
- SSH host key and machine-id regeneration after first boot must be audited
  separately. Other credentials, logs and network identities in a base image
  may still require manual sanitization; do not share an image without audit.
- Physical board compatibility must be proven by a separate, trusted adapter
  selecting the exact firmware, boot layout, DTB/ACPI and recovery procedure.
- NoCloud seed files are not passed to a booted VM by this builder: attach
  seed.iso or provide a NoCloud source using the chosen hypervisor separately.
- If optional status preview is active, the Skill emits rootfs-build progress.
  Otherwise no preview service or additional status file is created.

## Verification and troubleshooting

Run locally in an environment that has libguestfs/qemu-img:

~~~bash
python3 -m unittest discover -s tests -p 'test_rootfs_builder.py' -v
python3 -m unittest discover -s tests -v
~~~

Do **not** claim success unless those commands were really run. Some guests
have encrypted filesystems, LVM arrangements or files not supported by
libguestfs inspection. Fail closed and report the missing evidence; don't
guess a compatible guest configuration.

Reference implementation docs:
- https://libguestfs.org/virt-customize.1.html
- https://libguestfs.org/virt-sysprep.1.html
- https://libguestfs.org/virt-cat.1.html
