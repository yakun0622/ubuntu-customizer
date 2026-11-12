# First-boot health verification — AI Agent Skill contract

This is an **optional, explicitly approved Skill helper**, not a web control
panel. It validates one **new RootFS Builder VM bundle** in a transient,
isolated QEMU guest and does not modify its disk image. It is not a general
physical-board boot tester and never flashes hardware.

## Validation status

The implementation has passing Python tests using a fake local QGA socket
server and mocked QEMU execution. No actual BIOS/UEFI guest boot, restricted
DHCP behavior or physical-device boot is validated by those tests. See the
[validation record](roadmap.md#validation-record).

## Prerequisites

1. Use the existing `rootfs_builder.py --verify-bundle` to confirm source
   artifact checksums. The bundle must be a completed VM-only build with
   `build-manifest.json`, `build-config.json`, and a NoCloud seed.
2. Only **x86_64 / amd64** guests are supported in this stage. Other
   architectures are blocked until a separately reviewed adapter exists.
3. The guest MUST already have a **running QEMU Guest Agent** service and
   Python 3. The Skill does not install, enable or inject these components.
4. The build host needs `qemu-system-x86_64`, the existing qemu-img /
   libguestfs validation dependencies, and a NoCloud ISO tool
   (`genisoimage` or `mkisofs`) if the bundle lacks `seed.iso`.
5. For an inspected **UEFI** guest, supply both a trusted `OVMF_CODE.fd`
   and `OVMF_VARS.fd` template. The verifier clones VARS to a temporary
   directory. BIOS guests use the default QEMU BIOS. No automatic firmware
   selection from unverified host paths.
6. Ask the user for *new, explicit consent* to launch this isolated VM.
   Read-only evidence collection, build approval, or opting into the
   optional status preview are not permission to start QEMU.

## CLI

~~~bash
# The prior RootFS bundle must already be verified.
python3 scripts/workflow/rootfs_builder.py \
  --verify-bundle ./rootfs-bundle-001

# Explicit approval for a BIOS guest:
python3 scripts/workflow/verify_first_boot.py \
  --bundle ./rootfs-bundle-001 \
  --timeout 300 \
  --report ./first-boot-health.json \
  --approved

# UEFI guest: supply exact trusted firmware files.
python3 scripts/workflow/verify_first_boot.py \
  --bundle ./rootfs-bundle-001 \
  --ovmf-code /trusted/OVMF_CODE.fd \
  --ovmf-vars /trusted/OVMF_VARS.fd \
  --report ./first-boot-health.json \
  --approved
~~~

The verifier writes a new private JSON report and returns exit code **0 only
when all required guest health checks pass**. For incomplete verification,
failed checks, missing Guest Agent or preflight errors it returns nonzero
and keeps an actionable failure reason where feasible.

## Isolation and guest evidence

The verifier uses QEMU **TCG** (no privileged host accelerator required),
`-snapshot` (writes to disposable overlays instead of the source image),
`-netdev user,...,restrict=on` (guest DHCP but no host/Internet routing),
no port forwarding, no SSH access from host, no external UI port, and a
private local UNIX guest-agent socket under an ephemeral work directory.
The seed image is a verified `cidata` ISO: if missing from the bundle the
verifier builds one temporarily from verified seed files. On exit/timeout
QEMU is terminated, and the work directory and firmware VARS copy are
discarded. The published guest disk is re-hashed to prove it was not
modified by verification.

Actual first-boot evidence is collected **inside the running guest** using
a fixed Python probe launched via the QEMU Guest Agent. No arbitrary user
command, guest shell string, privileged host mounting or password operation
is accepted. A fresh random nonce must match the probe's response to prevent
old output being accepted. Health check results are booleans; the report also
contains metadata such as artifact hashes, status and a coarse reason.
It never persists raw machine-id, host keys, private key material or arbitrary
guest logs.

All of the following are required before `boot_confirmed=true`:

| Check | Actual evidence |
| --- | --- |
| linux_boot | Real guest /proc and valid randomized boot ID |
| system_state | `systemctl is-system-running` == running |
| cloud_init | `cloud-init status --format json` == done, no errors |
| instance_id | Guest cloud-init instance-data matches expected NoCloud instance ID |
| hostname | Guest system hostname matches build recipe |
| machine_id | Valid nonzero machine-id initialized at/after this boot |
| ssh_host_keys | Private/public host key pair present, permissions safe, key generated at/after this boot |
| ssh_service | ssh or sshd service is active |
| network | Guest has a non-loopback UP interface with an assigned IPv4 address |

If a check is false while the guest is still booting, the helper polls
again until the user-supplied deadline. A QEMU process exit, successful
Guest Agent ping, kernel serial output, or a successful cloud-init command
**on its own** does not count as boot success. Missing guest-agent service,
probe errors, timeout, mismatched nonce, network/cloud-init/SSH failures or
ambiguous boot evidence remain `blocked` or `failed`. The report includes
a boolean check matrix, coarse reason and provenance/status metadata, with no
raw machine identifiers.

The optional live Skill preview receives an allowlisted `verify` stage
through the same original device discovery session, if an approved preview
is currently live. No preview means no extra status output.

## Limits and next actions

- The result proves these **guest-visible properties** of one temporary
  QEMU boot with a particular firmware and virtual hardware model.
  Guest Agent data is not a cryptographic hardware attestation and does
  not guarantee future boots or physical-board compatibility.
- The first-boot network test validates interface status and local DHCP/IP
  only. Outbound Internet access is intentionally blocked and not tested.
- Non-amd64 images, missing qemu-guest-agent/Python, unsupported firmware,
  and images without a readable cloud-init instance ID need a separately
  approved adapter; this Skill never mutates the source image to force a
  passing test.
- A successful guest check does not certify that all machine-specific
  secrets were removed. Audit user data, service tokens, credentials,
  persistent network rules and license terms before sharing an image.
- Run the specific unit tests locally; mocked Guest Agent success is not
  evidence of an actual VM boot.

~~~bash
python3 -m unittest discover -s tests -p 'test_verify_first_boot.py' -v
python3 -m unittest discover -s tests -v
~~~

References:
- https://www.qemu.org/docs/master/interop/qemu-ga-ref
- https://www.qemu.org/docs/master/system/qemu-manpage.html
- https://docs.cloud-init.io/en/latest/reference/cli.html
