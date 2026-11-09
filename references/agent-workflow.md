# Agent-led workflow contract

The repository implements an **AI Agent Skill**, not a standalone control panel.
The conversational Agent owns workflow state, chooses scripts only when needed,
interprets evidence and pauses for user decisions. Scripts are disposable helpers;
their CLI prompts are not the primary user interface.

## Stages and required handoffs

### 1. Goal and transport
- Identify the user's goal: inspect, diagnose, maintain, recover, or create a portable image.
- Distinguish control host, build host, and target machine.
- Present appropriate access options: existing SSH Host, ADB, TTL serial, local.
- Ask for missing essential connection details, not an exhaustive form.
- Obtain authorization before connecting; do not assume tool availability.

### 2. Passive identification
- Begin with narrowly scoped, read-only identification.
- Prefer `scripts/workflow/adaptive.py` if execution and access exist.
- Gather OS, architecture, kernel, firmware/boot mode, storage and hardware capabilities.
- For TTL, receive logs passively only; do not send commands.
- Use `manifest.json` as the source of truth, record error and skipped probes.
- Avoid assuming a board model, a DTB, GPIO or PHY exists.

### 3. Evidence normalization
- Verify hashes before interpreting recorded evidence.
- Use `dossier.py`, `capabilities.py`, `topology.py`,
  `device_tree.py` and `link_graph.py` **only when the input evidence supports them**.
- The output is observed software topology, not guaranteed physical wiring.
- Show a short summary and explicit unknowns; ask user what to investigate or build.
- Offline HTML is optional presentation only, never the workflow coordinator.

### 4. Image portability decision
- Select a target class before choosing image format:
  virtual machine/cloud image, installer ISO, or physical board image.
- See `references/image-building.md` for backend and safety constraints.
- Demand trusted input source, independent checksum, license and source architecture.
- Check firmware/bootloader, storage layout, kernel, drivers, DT/ACPI and recovery.
- Use `image_plan.py` to **propose**, never to certify boot compatibility.
- For VM only, `build_image.py` can convert an existing image offline when
  the plan permits it. This does not migrate a running system or build a generic OS.
- For physical hardware, do not invoke a generic flashing or image builder:
  require a verified target adapter and explicit approval.
- Optional `nocloud.py` can make a first-boot seed for images already supporting
  cloud-init; it does not clean machine-specific state from the disk image.
- Optional `verify_vm.py` can check file metadata and run an explicitly
  requested isolated x86_64 QEMU smoke attempt. QEMU exit/timeout is not
  a successful guest boot assertion.

### 5. Approval, execution, verification
- Show planned operations, exact files, impact, recoverability and test criteria.
- Separate read-only inspection consent from image conversion, system changes,
  disk installation and flashing permissions.
- Never execute a blocked plan; do not bypass blockers by modifying plan JSON.
- Verify results from actual tool output, retain evidence and rollback details.
- Label untested code as untested. If execution access is missing, provide the
  exact script and explain what needs to be run on the user's host.

## Risk levels

- R0: passive read-only inspection and local interpretation
- R1: offline plans, data transforms, generated manifests
- R2: packages and ordinary service configuration (explicit approval)
- R3: SSH/network, kernel, firmware/DT changes (explicit recovery)
- R4: partitioning, device writes, flashing or installation (exact target and recovery)

## Prohibited shortcuts

- Do not infer physical pinout from DT nodes alone.
- Do not assume ARM64 Linux userspace implies firmware/board compatibility.
- Do not present raw-to-qcow2 conversion as successful image portability.
- Do not store credentials or automatically upload captured device data.
- Do not promote the optional terminal/web viewer into a required product layer.
