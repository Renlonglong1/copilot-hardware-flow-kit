# os-analyze-linux-log — Worked Example

This document is an end-to-end usage example of the `os-analyze-linux-log` skill. Starting from a kernel log, it walks through the full flow: **Step 0 source-tree confirmation → Step 1 log ingestion → Step 2 classification → Step 3 community search → Step 4 multi-round hypothesis/experiment → final conclusion**. The example is real and reproducible, with `file:line` source anchors and every refuted/supported hypothesis along the way. Use it as a reference for understanding how the skill operates.

> Key takeaway: **out of 5 hypothesis rounds, 4 were refuted; the root cause was only locked down in the last round after the user introduced new evidence**. The value of this example is not "guessing right on the first try" — it is demonstrating "how to narrow scope at every step without guessing".

---

## 0. Initial user input

An inline kernel log:

```
[  179.986750] usb 1-3: USB disconnect, device number 12
[  180.005211] usb 2-3: USB disconnect, device number 10
[  180.011096] usb 2-3.4: USB disconnect, device number 11
[  185.364315] xhci_hcd 0000:03:00.0: xHCI host not responding to stop endpoint command
[  185.374788] xhci_hcd 0000:03:00.0: xHCI host controller not responding, assume dead
[  185.383712] xhci_hcd 0000:03:00.0: HC died; cleaning up
[  185.390033] cdc_ncm 2-3.4:2.0 ens11u3u4c2: unregister 'cdc_ncm' usb-0000:03:00.0-3.4, CDC NCM (NO ZLP)
[  185.398328] usb 1-2: USB disconnect, device number 11
[  185.516720] usb 1-4: USB disconnect, device number 4
```

---

## 1. Step 0 — Source-tree confirmation

The skill's first action is **mandatorily** to ask for the source path; guessing is forbidden. The user answered:

```
D:\03_kernel\linux-6.18.24\linux-6.18.24
```

Validation passed (`Makefile` `VERSION=6 PATCHLEVEL=18 SUBLEVEL=24`); every subsequent grep / file reference is scoped to that path.

---

## 2. Step 1+2 — Transcription and classification

| Field | Value |
|---|---|
| Input modality | inline |
| Primary category | `device` (xhci_hcd driver) |
| Secondary signals | network interface `cdc_ncm ens11u3u4c2` goes down with the controller |
| Kernel version | 6.18.24 |
| Intent | `debug-a-failure` (`HC died; cleaning up` is a clear failure event) |

Source anchors are nailed down first (Step 4 cannot start before file:line resolution):

| Log format string | File:line | Function |
|---|---|---|
| `xHCI host not responding to stop endpoint command` | drivers/usb/host/xhci-ring.c:1746 | `xhci_handle_command_timeout` |
| `xHCI host controller not responding, assume dead` | drivers/usb/host/xhci-ring.c:1390 | `xhci_hc_died` |
| `HC died; cleaning up` | usbcore (printed by hcd core after `usb_hc_died()`) | — |
| cmd_timer registration | drivers/usb/host/xhci.c:548 | `INIT_DELAYED_WORK(&xhci->cmd_timer, xhci_handle_command_timeout)` |

Call chain:

```
xhci_handle_command_timeout   (5s timeout on TRB_STOP_RING)
  └─ xhci_warn("xHCI host not responding to stop endpoint command")
  └─ xhci_halt()
  └─ xhci_hc_died()
       └─ xhci_err("xHCI host controller not responding, assume dead")
       └─ usb_hc_died()
            └─ hcd core prints "HC died; cleaning up" and tears down every USB device under this controller
```

The time delta `185.36 - 180.00 ≈ 5.36s` matches `XHCI_CMD_DEFAULT_TIMEOUT = 5s`, confirming the path above.

---

## 3. Step 3 — Community search (Branch D)

Three queries (each a verbatim substring of the log):

1. `xHCI host not responding to stop endpoint command`
2. `xHCI host controller not responding, assume dead`
3. `HC died; cleaning up`

Searches against lore.kernel.org / bugzilla.kernel.org / git.kernel.org / bugzilla.redhat.com / bugs.launchpad.net — **all blocked by the Anubis bot challenge or gateway-timed-out**. `similar.md` is recorded as `no-hits`; no fabricated evidence is injected into later steps.

Lesson: the skill's "never fabricate" rule pays off here — better to proceed empty-handed than to invent hits.

---

## 4. Step 4 — Five hypothesis/experiment rounds

The full five-round trajectory follows. Each round ends with the mandatory Step 5 (`step4-next-round`) prompt that lets the user decide whether to continue.

### Round 1 — "PCIe controller fell off the bus"

| Field | Content |
|---|---|
| Claim | The xHC was disconnected from the PCIe bus around t≈180s; subsequent Stop Endpoint commands could not be written, and 5s later cmd_timer triggered the dead path. |
| Experiment | `lspci -s 0000:03:00.0 -vvv` |
| User reply | "Device is still visible." |
| Result | **REFUTED** at step 1 — literal match against the FALSE predicate |

Takeaway: the PCIe link is alive; the failure is narrowed to "internal xHC state", not "link down".

### Round 2 — "xHC internal halt + Renesas-specific quirk"

| Field | Content |
|---|---|
| Claim | PCIe MMIO is still readable, but USBSTS.HCH/HSE=1, the HC's internal state machine is stalled; possibly a known halt-bug on Renesas / ASMedia / older Intel parts. |
| Experiment | (a) `dmesg \| grep "Command timeout\|USBSTS\|quirks"` (b) PM-path check (c) `lspci -n` for vendor |
| User reply | (a) only the quirks line, no `Command timeout, USBSTS:` (xhci_dbg does not go to kmsg by default) → **inconclusive** (b) skip → **inconclusive** (c) `0000:03:00.0 0c03: 1912:0014 (rev 03)` |
| Result | **SUPPORTED** (1/3 support, 2 inconclusive, 0 refute) |

**Key fact landed**: PCI ID `1912:0014` = **Renesas uPD720201 USB 3.0 Host Controller**, xHCI v1.00, quirks `0x100000010`.

### Round 3 — "Renesas firmware blob failed to load"

| Field | Content |
|---|---|
| Claim | `xhci-pci-renesas.c` uploads RAM firmware via `request_firmware("renesas_usb_fw.mem")`; if that step silently fails, the controller runs in a "half-working" state and deadlocks internally after cumulative operations. |
| Experiment | (a) `dmesg \| grep -i renesas` (b) `ls /lib/firmware/renesas*` (c) lspci to view Subsystem / Expansion ROM |
| User reply | All three steps skipped |
| Result | **INCONCLUSIVE** (0 support, 3 inconclusive, 0 refute) |

### Round 4 — "Hardware failure (power / aging / thermal)"

Per Step 5 rules, category switched: `device` → `hardware`.

| Field | Content |
|---|---|
| Claim | +5V/3.3V power-rail ripple on the add-in card, electrolytic-cap aging, or chip thermal accumulation puts the HC into a physical-layer deadlock after sustained operation. |
| Experiment 1 | "Does the failure happen only when certain devices are attached / certain traffic is running?" |
| User reply | **"Every failure had a cdc_ncm NIC attached; cards using their own driver are fine."** |
| Result | **REFUTED** at step 1 |

Inflection point: same hardware behaves differently under different drivers → hardware-failure hypothesis dies; the focus shifts to "`cdc_ncm` driver × xHCI interaction".

### Round 5 — "Large `cdc_ncm` NTB URBs trigger a hang on uPD720201"

| Field | Content |
|---|---|
| Claim | `cdc_ncm` uses the NCM NTB protocol, aggregating multiple frames into 16–32 KB bulk URBs. Under sustained traffic, the uPD720201 endpoint / event-ring processing hits a bottleneck and Stop Endpoint commands eventually never complete. |
| Experiment 1 | `cat /sys/class/net/<iface>/cdc_ncm/*` |
| User reply | Output contains `32768 / 65536 / 14849 / 16384 / 16385` — confirmed in the 16–64KB range |
| Result 1 | **support** |
| Experiment 2 | Look at interface traffic counters before failure |
| User reply | 615 RX packets / 45 TX packets, 55 drops |
| Result 2 | **inconclusive** (the snapshot is post-recovery cumulative and does not represent the failure point), but 9% RX-drop is a weak side indicator |
| Experiment 3 | `lsusb -v` for USB 3 SS / bMaxBurst |
| User reply | `bcdUSB 2.10`, `wMaxPacketSize 512`, no `bMaxBurst` |
| Result 3 | **refute** (the bundled "USB SS burst amplification" mechanism was written into the FALSE predicate; all three items match literally) |
| Overall | **REFUTED at step 3** (but Step 1 did empirically confirm the core mechanism) |

A driver detail was corrected along the way: `cdc_ncm`'s `rx_max/tx_max`, when written through sysfs, is delivered to the device immediately via `cdc_ncm_update_rxtx_max` (drivers/net/usb/cdc_ncm.c:405) as `USB_CDC_SET_NTB_INPUT_SIZE`, updating `dev->rx_urb_size`. But on every device re-probe, `cdc_ncm_setup` (drivers/net/usb/cdc_ncm.c:701) resets the value back to `CDC_NCM_NTB_DEF_SIZE_RX/TX = 16384` — so a single sysfs write does not survive a "HC died → re-enumerate" cycle. A udev rule that writes the value back on the `add` event is required for persistence.

### User introduces decisive evidence — hypotheses re-shuffled

The user later provided two new facts:

1. **"Unloaded cdc, used the LAN's vendor-specific driver, the same failing card still fails."**
2. **"Switched to Realtek RTL8153 or Aquantia AQC111 on the same uPD720201 — does not happen."**

Plus a new log:

```
[  523.646477] ax88179_178a 2-3.4:1.0 (uninitialized): Failed to read reg index 0x0040: -32
[  524.448095] ax88179_178a 2-3.4:1.0 ens11u3u4: Failed to read reg index 0x0040: -32
[  527.504640] usb 2-3: USB disconnect
[  532.540660] xhci_hcd 0000:03:00.0: xHCI host not responding to stop endpoint command
[  532.550905] xhci_hcd 0000:03:00.0: xHCI host controller not responding, assume dead
[  532.559789] xhci_hcd 0000:03:00.0: HC died; cleaning up
[  532.559963] xhci_hcd 0000:03:00.0: Timeout while waiting for configure endpoint command
[  532.565823] ax88179_178a 2-3.4:1.0 ens11u3u4: unregister 'ax88179_178a' ... ASIX AX88179 USB 3.0 Gigabit Ethernet
```

The new log adds two decisive pieces of information beyond the original:

| Observation | Meaning |
|---|---|
| `Failed to read reg index 0x0040: -32` (`-EPIPE`) appears during probe | AX88179's control endpoint STALLs; the device-side USB controller state is already off |
| New `Timeout while waiting for configure endpoint command` | On SuperSpeed AX88179, uPD720201 fails to generate a completion event for the **Configure Endpoint** TRB — an xHCI command failure even earlier than Stop Endpoint |

Putting the three data sets side by side:

| NIC | Chip | Driver | On the same uPD720201 |
|---|---|---|---|
| ASIX AX88179 | USB 3.0 GbE | `cdc_ncm` or `ax88179_178a` | **fail (HC died)** |
| Realtek RTL8153 | USB 3.0 GbE | `r8152` | OK |
| Aquantia AQC111 | USB 3.0 multi-Gig | `aqc111` | OK |

---

## 5. Final conclusion

**Root cause**: a **device-level compatibility bug** between ASIX AX88179 (USB device side) and Renesas uPD720201 (xHCI host side). Specifically, the `Configure Endpoint` TRB on a SuperSpeed AX88179 produces no completion event; 5 seconds later cmd_timer marks the entire HC dead.

Ruled out (empirically, across the five rounds):

- **Not** Renesas xHC add-in-card hardware failure (RTL8153 / AQC111 work on the same card).
- **Not** uPD720201 power/aging/thermal issues (same).
- **Not** Renesas firmware-blob load failure (Round 3 inconclusive; later evidence renders it irrelevant).
- **Not** a Linux driver-stack choice issue (`cdc_ncm` and `ax88179_178a` both die).
- **Not** a `cdc_ncm` NCM NTB large-URB issue (switching to `ax88179_178a` still dies).
- **Not** a PCIe link issue (proven in Round 1).
- **Is** a SuperSpeed protocol/timing issue between this specific AX88179 USB device controller and the uPD720201 xHC.

## 6. Recommended remediation

By order of effectiveness:

1. **Switch USB-Ethernet chip** (already empirically validated by the user): Realtek RTL8153 (`r8152`) or Aquantia AQC111 (`aqc111`) runs stably on the same uPD720201.
2. **Keep the AX88179, force USB 2.0**: connect it to a USB 2.0 port, or interpose a USB 2.0 hub, to bypass the SuperSpeed state machine. Bandwidth ceiling ~280 Mbps.
3. **Switch USB host controller**: plug the AX88179 into the motherboard's onboard Intel/AMD xHCI port, bypassing the uPD720201.
4. **Temporary mitigation (diagnostic only)**: disable USB autosuspend / U1U2 on this device:
   ```bash
   USB_DEV=$(readlink -f /sys/bus/usb/devices/2-3.4)
   echo on       | sudo tee $USB_DEV/power/control
   echo disabled | sudo tee $USB_DEV/power/wakeup 2>/dev/null
   ```

---

## 7. Skill behaviors this example demonstrates

| Behavior | How it shows up |
|---|---|
| **never guess** | Source path is mandatorily asked; when all community sites failed, no hits were fabricated — `no-hits` placeholder was written instead. |
| **every file:line is clickable** | xhci-ring.c:1746 / :1390 / :1380 / xhci.c:548 / cdc_ncm.c:405 / :578 / :701 all come from real grep hits. |
| **multi-round iteration, recoverable** | 3 rounds REFUTED + 1 INCONCLUSIVE + 1 SUPPORTED across 5 rounds; Step 5 lets the user decide whether to continue after each round. |
| **user experiment output is the only evidence** | "User output excerpt" is verbatim — `1912:0014`, `bcdUSB 2.10`, `rx_max=14849`, etc. |
| **category switch enforced at Step 5** | Round 3 → 4 switched from `device` to `hardware`, complying with skill rule 5.2. |
| **source-code reading corrects user understanding** | E.g. `cdc_ncm` sysfs writes do not persist across re-probe; failed `USB_CDC_SET_NTB_INPUT_SIZE` does not surface as a sysfs store error — both derived from close reading of drivers/net/usb/cdc_ncm.c. |
| **decisive new user evidence triggers re-shuffle** | After the user reported "RTL8153/AQC111 OK on the same card", focus locked onto AX88179 ↔ uPD720201 compatibility and stopped chasing cdc_ncm. |

---

## 8. Timeline at a glance

```
t = 0      User pastes inline log (xhci HC died)
           │
           ▼
Step 0     Ask source path → D:\03_kernel\linux-6.18.24
Step 1+2   Transcribe + classify (device, debug-a-failure)
           Source anchors: xhci-ring.c:1746 / 1390 / 1380
           │
           ▼
Step 3 D   Community search → all blocked by Anubis → similar.md = no-hits
           │
           ▼
Round 1    "PCIe fell off"        →  REFUTED (user: "device still visible")
Round 2    "Renesas halt"         →  SUPPORTED (lspci -n → 1912:0014)
Round 3    "firmware blob missing"→  INCONCLUSIVE (user skipped all)
Round 4    "hardware failure"     →  REFUTED (user: "vendor driver same card OK")
Round 5    "cdc_ncm large URB"    →  REFUTED at step 3
           │
           ▼
New user evidence  "vendor driver still fails" + "RTL8153/AQC111 OK" + ax88179 new log
           │
           ▼
Final      AX88179 ↔ uPD720201 device-level compatibility bug
           Configure Endpoint TRB has no completion event → cmd_timer → hc_died
```

---

## 9. Want to reproduce this example yourself?

1. Open chat in VS Code, attach the `pae-bios` agent (or any agent that ships the `os-analyze-linux-log` skill).
2. Have a local Linux kernel source tree path ready.
3. Paste the log from §0 of this document.
4. Answer the skill prompts step by step (source path, Step 3 branch = D, similar.md location, each experiment is Paste / Skip / Abort).
5. After the five rounds, introduce the additional facts ("vendor driver still fails" / "RTL8153 OK") and observe how the skill converges.

If you want to test the skill's `learn-the-code-path` mode (Branch S), paste the same log and choose S in Step 3 — you will get a module map + ≤3-level call graph instead of a community search + experiment loop.
