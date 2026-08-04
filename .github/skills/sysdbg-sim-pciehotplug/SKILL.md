---
name: sysdbg-sim-pciehotplug
description: "Simulate PCIe hot-plug (surprise hot-remove + hot-insert) on an Intel server Root Port via CScripts/PythonSV, and answer PCIe hot-plug related debug questions (DPC, AER, ACS Violation, LTSSM link bounce, VPP/Power Controller, slot capability, pciehp). Use this skill whenever the user asks to: simulate hot-plug, surprise remove, hot insert, link bounce, linkdisable/linkenable a PCIe port, toggle linkctl.ld, do PCIe SBR, recover from DPC contained, clear dpcsts, decode slotcap/slotsts/slotctl, mask erruncmsk acsem/sldem, troubleshoot 'DPC keeps re-triggering', 'link wont come back', 'ACS Violation persistent', 'cant clear dpcts', explain pds/pdcs, VPP virtual pin port, PERST# behavior, why hot-plug needs pcp/vppe, why OS lost root disk after link bounce, NVMe nvme0/nvme1 double enumeration after rescan. Trigger phrases: PCIe hot-plug, 热插拔, 模拟热插拔, link bounce, surprise down, DPC lockup, DPC contained, ACS Violation, linkdisable, linkenable, linkretrain, slot capability, VPP, PERST, pciehp, hot-add, hot-remove, port 0e, root port, RP hotplug."
---

# PCIe Hot-Plug Simulation & Debug

End-to-end workflow for simulating PCIe surprise hot-remove + hot-insert on an Intel server platform via CScripts/PythonSV, and answering related debug questions. Built from real BHS/SRF experiments on port 0e (see `port0e_hotplug_test_report.md` if present in the workspace).

---

## 1. Hard Prerequisites — CHECK BEFORE TOUCHING ANYTHING

Before issuing **any** disruptive PCIe command, verify these. Skipping any of them risks **bricking the running OS**.

### 1.1 Is the target port the OS root disk?

| Check | How |
|---|---|
| Does the SSD/NIC under the target RP host the OS rootfs / boot / swap? | OS side: `lsblk`, `cat /proc/mounts`, `findmnt /` |
| Does it carry the management NIC? | `ip route show default` |

> **🛑 If yes → STOP. Do NOT do LTSSM-level link bounce on this port.**
> 
> Even if `linkctl.ld` toggle "succeeds" and link comes back, the kernel block layer has already marked the NVMe queue *dying*; rootfs becomes IO-error, all `/usr/bin/*` commands return "command not found". Only recovery is **reboot**. See §7.

### 1.2 Does BIOS have hot-plug enabled on this slot?

```python
p = sv.socket0.io0.uncore.pi5.pxp0.rp<N>   # adjust path per port
print(f"hpc={p.cfg.slotcap.hpc} hps={p.cfg.slotcap.hps}")
```

- `hpc=1, hps=1` → ✅ proceed
- `hpc=0` → ❌ go to BIOS, enable PCIe hot-plug for this slot, reboot, retry. Otherwise `linkdisable` will trigger ACS Violation → DPC contain → port locks up.

### 1.3 Does the slot have real hot-plug hardware?

```python
print(f"pcp={p.cfg.slotcap.pcp} vppe={p.cfg.vppcsr.vppe}")
```

| Combination | Meaning | Can do real hot-plug? |
|---|---|---|
| `pcp=1` | Slot has Power Controller | ✅ Yes — `slotctl.pcc` cycles PWREN# |
| `vppe=1` | VPP active, SMBus expander wired | ✅ Yes — VPP drives PRSNT#/PWREN#/PERST# |
| both `0` | Bare connector, no power/PRSNT control | ⚠️ Only LTSSM link bounce possible (not a true hot-plug) |

### 1.4 Current link state baseline

```python
print(f"ld={p.cfg.linkctl.ld} dllla={p.cfg.linksts.dllla} cls={p.cfg.linksts.cls} "
      f"nlw={p.cfg.linksts.nlw} pds={p.cfg.slotsts.pds} dpcts={p.cfg.dpcsts.dpcts} "
      f"erruncsts=0x{p.cfg.erruncsts.read():x}")
```

Healthy baseline: `ld=0, dllla=1, cls!=0, nlw>0, pds=1, dpcts=0, erruncsts=0`.

---

## 2. The Safe Sequence (Mandatory Order)

> **Golden rule**: mask the trigger sources **before** any disruptive action. ACS Violation is per-TLP edge-triggered (§9), not link-state edge — once link goes down, the OS continues to push TLPs which the RP keeps faulting, repeatedly re-arming DPC. You cannot W1C-clear faster than it re-arms (§8).

### Step 1 — Disarm DPC re-trigger loop ★ MUST be first

```python
import time
p = sv.socket0.io0.uncore.pi5.pxp0.rp<N>

p.cfg.dpcctl.dpcie    = 0    # disable DPC trigger
p.cfg.erruncmsk.acsem = 1    # mask ACS Violation (bit 21)
p.cfg.erruncmsk.sldem = 1    # mask Surprise Down (bit 5)

print(f"dpcie={p.cfg.dpcctl.dpcie} acsem={p.cfg.erruncmsk.acsem} sldem={p.cfg.erruncmsk.sldem}")
# Expected: dpcie=0x0 acsem=0x1 sldem=0x1
```

**Field-name pitfall**: spec mnemonics ≠ CScripts field names.

| Standard name | CScripts field name | Bit |
|---|---|---|
| ACS Violation Mask | `acsem` | 21 |
| Surprise Down Mask | `sldem` | 5 |

Use `p.cfg.erruncmsk.show()` to enumerate the actual names — do NOT guess (`acsvm`/`sdes` are wrong).

### Step 2 — Surprise hot-remove

```python
pcie.linkdisable(0, '0e')     # or: p.cfg.linkctl.ld = 1
time.sleep(1)
print(f"ld={p.cfg.linkctl.ld} dllla={p.cfg.linksts.dllla} pds={p.cfg.slotsts.pds} "
      f"pdcs={p.cfg.slotsts.pdcs} dllscs={p.cfg.slotsts.dllscs} "
      f"dpcts={p.cfg.dpcsts.dpcts} erruncsts=0x{p.cfg.erruncsts.read():x}")
```

Expected after a *clean* surprise remove (mask in place, no real PRSNT# change):

```
ld=1 dllla=0 pds=1 pdcs=0 dllscs=1 dpcts=0 erruncsts=0
```

Notes:
- `dllscs=1` ✅ link state changed latched
- `pds=1, pdcs=0` ⚠️ Presence Detect did NOT change → this is link bounce, not physical removal (§6)
- `dpcts=0, erruncsts=0` ✅ trigger was successfully masked

### Step 3 — Hot-insert (link retrain)

```python
p.cfg.linkctl.ld = 0
time.sleep(0.05)
p.cfg.linkctl.rl = 1          # force retrain
time.sleep(3)
print(f"ld={p.cfg.linkctl.ld} dllla={p.cfg.linksts.dllla} cls={p.cfg.linksts.cls} "
      f"nlw={p.cfg.linksts.nlw} pds={p.cfg.slotsts.pds} dpcts={p.cfg.dpcsts.dpcts} "
      f"erruncsts=0x{p.cfg.erruncsts.read():x}")
```

Expected: `ld=0 dllla=1 cls=<original> nlw=<original> dpcts=0 erruncsts=0`.

### Step 4 — (Optional) PERST# pulse via VPP

Only if `vppe=1`:

```python
# Implementation depends on board's VPP wiring; typically:
p.cfg.vppctl.pwren = 0    # power off
time.sleep(0.5)
p.cfg.vppctl.pwren = 1    # power on
```

If `vppe=0`, **skip this step**. There is no PERST# you can drive from software.

### Step 5 — Verify topology re-enumeration

```python
pcie.topology(0)                    # confirm device returned
pcie.logshort(0, '0e')              # link summary
```

---

## 3. CScripts Hot-Plug Command Reference

### 3.1 Information

| Command | Purpose |
|---|---|
| `pcie.topology(socket)` | Full PCIe topology, link width, speed, state |
| `pcie.hotplug(socket, cluster)` | Dump SlotCap / SlotCtrl / SlotSts / LnkCap / VPPCSR / AER UncMsk |
| `pcie.logshort(socket, port)` | Per-port LTSSM + Link summary |
| `pcie.link_check(socket, port)` | Validate link configuration consistency |

### 3.2 Disruptive (use only after Section 2 §1)

| Command | Effect |
|---|---|
| `pcie.linkdisable(socket, port)` | `linkctl.ld=1` → link Down |
| `pcie.linkenable(socket, port)` | `linkctl.ld=0` → link recover |
| `pcie.linkretrain(socket, port)` | `linkctl.rl=1` |
| `pcie.sbr(socket, port)` | Secondary Bus Reset (⚠️ triggers ACS Violation if DPC armed — see §8) |

### 3.3 Direct register access (when CScripts wrappers don't fit)

```python
p = sv.socket0.io0.uncore.pi5.pxp<X>.rp<N>     # adjust path

p.cfg.linkctl       # link control (ld, rl, ...)
p.cfg.linksts       # link status (dllla, cls, nlw, ...)
p.cfg.slotcap       # slot caps (hpc, hps, pcp, ...)
p.cfg.slotctl       # slot control (pcc, abpe, hpie, ...)
p.cfg.slotsts       # slot status (pds, pdcs, dllscs, abp, ...)
p.cfg.vppcsr        # VPP main (vppe, vppaddr, vpppin)
p.cfg.vppctl        # VPP outputs (pwren, atnled, pwrled)
p.cfg.vppsts        # VPP inputs (pds, mrlsensor, pwrflt, atnbtn)
p.cfg.dpcctl        # DPC control (dpcie, dpcte)
p.cfg.dpcsts        # DPC status (dpcts) — RW1C with re-arm semantics (§8)
p.cfg.erruncsts     # AER uncorrectable status
p.cfg.erruncmsk     # AER uncorrectable mask
```

To enumerate a register's actual field names: `p.cfg.<reg>.show()`.

---

## 4. Locating the Right namednode Path

Pattern: `sv.socket<S>.io<I>.uncore.pi<P>.pxp<X>.rp<N>` where:

- `<S>` = socket (0..n)
- `<I>` = IO die (typically 0 on SRF/GNR)
- `<P>` = PCIe controller cluster (pi5 on SRF/BHS for the CPU PCIe cluster of interest)
- `<X>` = PXP / port group (pxp0, pxp1, ...)
- `<N>` = root port within the cluster (rp0, rp1, rp2, ...)

If unsure, navigate interactively:

```python
dir(sv.socket0.io0.uncore)
dir(sv.socket0.io0.uncore.pi5)
dir(sv.socket0.io0.uncore.pi5.pxp0)
```

`pcie.topology(0)` lists port number (e.g. `0e`) → cross-map to rpN by inspecting bus assignments.

---

## 5. Recovery from DPC Lockup

If you forgot Step 1 of §2 and the port is now DPC-contained (`dpcts=1`, link wedged):

```python
# (a) FIRST disarm the trigger source — order matters
p.cfg.erruncmsk.acsem = 1
p.cfg.erruncmsk.sldem = 1
p.cfg.dpcctl.dpcie    = 0

# (b) Clear DPC source register
p.cfg.dpcsr.write(0xffff)         # W1C all source bits

# (c) Clear AER status
p.cfg.erruncsts.write(0xffffffff)

# (d) Now W1C dpcts will stick
p.cfg.dpcsts.dpcts = 1

# (e) Bring link back
p.cfg.linkctl.ld = 1
time.sleep(0.1)
p.cfg.linkctl.ld = 0
p.cfg.linkctl.rl = 1
```

If link still won't recover:
- Check whether downstream device received PERST# (it didn't, unless `vppe=1` was driven)
- For Samsung NVMe and similar simple endpoints: link will retrain automatically once RP exits Disabled, *provided* the device is still powered
- Last resort: `itp.resettarget()` from CScripts/PythonSV → full warm reset

> **Never run `pcie.sbr()` while DPC is armed.** SBR sends a TLP to a contained downstream → re-triggers ACS Violation → re-arms DPC → infinite loop.

---

## 6. Concept: Link Bounce vs Real Hot-Plug

This is the most-misunderstood point. Without `pcp=1` or `vppe=1`, what you do is **NOT** a real hot-plug.

| Action | Link bounce (`linkctl.ld` toggle) | Real hot-plug (VPP/PCP) |
|---|---|---|
| LTSSM Disabled state | ✅ | ✅ |
| Power off downstream device | ❌ never | ✅ PWREN# off |
| Assert PERST# | ❌ never | ✅ |
| PRSNT# transitions | ❌ never | ✅ |
| `slotsts.pds` changes (1→0→1) | ❌ stays 1 | ✅ |
| `slotsts.pdcs` latches | ❌ stays 0 | ✅ |
| `pciehp` driver hot-remove IRQ | ❌ | ✅ |
| OS unbinds device driver | ❌ | ✅ |
| Net effect | LTSSM bounce + zombie kernel state | Clean remove + clean re-add |

**Why link does come back even without VPP**: device stays powered & inserted; once RP leaves Disabled, the endpoint immediately retrains in physical layer.

**Why this is dangerous**: kernel block layer marks queues *dying* on Link Down event but never gets a corresponding hot-add to re-bind. Result is a zombie state — link is up at PCIe layer but the OS still sees a dead disk. See §7.

---

## 7. The OS-Side Catastrophe (and why §1.1 matters)

After link bounce on a port that hosts a mounted filesystem:

```
linkctl.ld=1                         (microseconds)
   ↓
RP reports Link Down → kernel pciehp/AER
   ↓
nvme<N> request_queue marked DYING
   ↓
in-flight I/O returns EIO
   ↓
ext4/xfs remounts root R/O or errors=remount
   ↓
page cache miss → read disk → EIO
   ↓
bash stat() of /usr/bin/<cmd> → fails → "command not found"
```

Symptoms:
- `cat`, `tail`, `ls`, `dmesg`, `reboot` all "command not found"
- bash builtins (`echo`, `cd`, `type`, `pwd`, `help`) still work
- dmesg often shows **double enumeration**: original `nvme0` is dying, kernel rescans link-up event and registers a NEW `nvme1` (or `nvme0n2`) for the same physical SSD, but `/etc/fstab` still points at the old path → unrecoverable

Recovery (use only bash builtins, no `/usr/bin`):

```bash
echo 1 > /proc/sys/kernel/sysrq
echo b > /proc/sysrq-trigger          # immediate reboot
```

Or from OOB CScripts:

```python
itp.resettarget()
```

---

## 8. Concept: Why DPC `dpcsts` Won't Clear

PCIe spec for `dpcsts.dpcts`:

> Software writes 1 to clear DPC Trigger Status. **However, the bit will remain set if the DPC trigger condition is still being indicated by the source.**

W1C ≠ unconditional clear. It's "try to clear, but hardware can immediately re-arm".

The lockup loop:

```
linkctl.ld=1 → link Down → continuous ACS Violation (§9)
   ↓
ACS Violation routed to DPC (per dpcctl.dpcte) → dpcsts.dpcts=1
   ↓
You write dpcts=1 (W1C)
   ↓
Hardware checks: is the source still asserted? YES
   ↓
dpcts immediately re-armed back to 1 → looks like "stuck"
```

Escape order: mask source FIRST, clear trigger source register, clear AER status, THEN W1C dpcts. See §5.

---

## 9. Concept: Why ACS Violation is Persistent After Link Down

ACS Violation is **per-TLP edge-triggered**, not link-state edge-triggered.

After `linkctl.ld=1`:

```
CPU/IOMMU/DMA agents still believe BDF on bus 0e is alive
   ↓
Continue issuing outbound TLPs (cfg reads, MSI routing, DMA completions)
   ↓
TLP reaches RP TX
   ↓
RP sees link state Disabled → cannot forward
   ↓
RP self-generates UR Completion
   ↓
Self-generated completion routes inside RP with mismatched src/dst BDF
   ↓
ACS check fails → erruncsts.acsvm latched
   ↓
Repeats at the cadence of upstream traffic (every ms or faster)
```

Sources that keep injecting traffic during Link Down:

| Source | Cadence |
|---|---|
| OS sysfs / lspci / pcie_aer poll | ~1 Hz |
| AER/DPC IRQ handler doing follow-up cfg reads | per event |
| MSI-X table updates | sporadic |
| In-flight DMA completions before timeout | seconds |
| Peer-to-peer routing checks from other ports | per TLP |

**Mask vs clear**:

| Operation | Effect |
|---|---|
| `erruncsts.acsvm = 1` (W1C status) | Clears latch — next offending TLP re-sets it. **Useless.** |
| `erruncmsk.acsem = 1` (set mask) | Disables the reporting signal path. Errors still happen physically but never propagate to status / DPC. **Correct.** |

**Why ACSV dominates over SDE/UR on SRF/EGS**:

| Error | Trigger style |
|---|---|
| Surprise Down (SDE) | Edge — fires once at link state change |
| Unsupported Request (UR) | Per-TLP, but masked earlier in pipeline by default |
| ACS Violation (ACSV) | Per-TLP, **first stage** of error pipeline on Intel SRF/EGS |

So link bounce → ACSV is what you'll see latched first and continuously.

---

## 10. Quick Decision Tree for User Questions

| User asks | Section to consult |
|---|---|
| "How do I simulate hot-plug on port X?" | §1 → §2 |
| "What CScripts commands exist for hot-plug?" | §3 |
| "How do I find the namednode path?" | §4 |
| "DPC won't clear / dpcts stuck at 1" | §5 + §8 |
| "ACS Violation keeps firing after I cleared it" | §9 |
| "Link came back but OS still doesn't see device" | §6 + §7 |
| "Why does my OS lose `cat`/`tail` after link bounce?" | §7 |
| "Why doesn't `vppe=0` matter when link still recovered?" | §6 |
| "Should I use SBR to recover?" | §5 (warning) |
| "Why is `slotsts.pds` not changing?" | §6 |

---

## 11. Hard Rules (do not violate)

1. ❌ Never disrupt PCIe on the OS root disk RP. Verify with §1.1.
2. ❌ Never call `linkdisable`/`sbr` before doing §2 Step 1 (mask ACSV+SDE, disable DPC).
3. ❌ Never trust spec mnemonics for CScripts field names — call `.show()` first.
4. ❌ Never run `pcie.sbr()` while `dpcsts.dpcts=1` is armed.
5. ❌ Never claim "hot-plug works" on a slot with `pcp=0, vppe=0` — it's link bounce, not hot-plug.
6. ✅ Always capture baseline (§1.4) before and after each step.
7. ✅ Always have an OOB recovery path ready (`itp.resettarget()`).
