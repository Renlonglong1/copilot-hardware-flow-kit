#!/usr/bin/env python3
"""Interactive GUI launcher for bios-platform-knob-export."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PLATFORM_ROOTS = {
    "EGS": Path(r"D:/Code/Gen2"),
    "BHS": Path(r"D:/Code/ServerGen3"),
    "OKS": Path(r"D:/Code/dmr_bios"),
}


def default_intel_path(platform: str) -> str:
    return str((PLATFORM_ROOTS[platform] / "Intel").resolve())

SCRIPT_DIR = Path(__file__).resolve().parent
EXPORTER = SCRIPT_DIR / "export_bios_knobs.py"


def run_export(platform: str, bios_path: str, out_xlsx: str) -> int:
    cmd = [
        sys.executable,
        str(EXPORTER),
        "--platform",
        platform,
        "--output",
        out_xlsx,
    ]
    if bios_path.strip():
        cmd.extend(["--bios-path", bios_path.strip()])
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


def fallback_cli() -> int:
    print("[Info] GUI unavailable, using CLI interactive mode.")
    print("Choose platform: EGS / BHS / OKS")
    platform = input("Platform [OKS]: ").strip().upper() or "OKS"
    if platform not in PLATFORM_ROOTS:
        print(f"Invalid platform: {platform}")
        return 2

    default_bios = default_intel_path(platform)
    bios_path = input(f"BIOS path [{default_bios}]: ").strip() or default_bios
    default_out = str((Path.cwd() / "reports" / f"{platform.lower()}_knobs.xlsx").resolve())
    out_xlsx = input(f"Output xlsx [{default_out}]: ").strip() or default_out
    return run_export(platform, bios_path, out_xlsx)


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception:
        return fallback_cli()

    root = tk.Tk()
    root.title("BIOS Knob Export")
    root.geometry("760x250")

    platform_var = tk.StringVar(value="OKS")
    bios_path_var = tk.StringVar(value=default_intel_path("OKS"))
    default_out = str((Path.cwd() / "reports" / "oks_knobs.xlsx").resolve())
    out_path_var = tk.StringVar(value=default_out)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text="Platform").grid(row=0, column=0, sticky="w", pady=6)
    platform_combo = ttk.Combobox(frame, textvariable=platform_var, values=["EGS", "BHS", "OKS"], state="readonly", width=12)
    platform_combo.grid(row=0, column=1, sticky="w", pady=6)

    def on_platform_change(_event=None) -> None:
        platform = platform_var.get().strip().upper()
        if platform not in PLATFORM_ROOTS:
            return
        bios_path_var.set(default_intel_path(platform))
        out_path_var.set(str((Path.cwd() / "reports" / f"{platform.lower()}_knobs.xlsx").resolve()))

    platform_combo.bind("<<ComboboxSelected>>", on_platform_change)

    ttk.Label(frame, text="BIOS path (must be under platform Intel root)").grid(row=1, column=0, sticky="w", pady=6)
    bios_entry = ttk.Entry(frame, textvariable=bios_path_var, width=78)
    bios_entry.grid(row=2, column=0, columnspan=2, sticky="we", pady=3)

    def browse_bios() -> None:
        path = filedialog.askdirectory(title="Select BIOS source path")
        if path:
            bios_path_var.set(path)

    ttk.Button(frame, text="Browse BIOS Path", command=browse_bios).grid(row=2, column=2, padx=8, pady=3)

    ttk.Label(frame, text="Output Excel path").grid(row=3, column=0, sticky="w", pady=6)
    out_entry = ttk.Entry(frame, textvariable=out_path_var, width=78)
    out_entry.grid(row=4, column=0, columnspan=2, sticky="we", pady=3)

    def browse_out() -> None:
        path = filedialog.asksaveasfilename(
            title="Save exported knob table",
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx")],
            initialfile=f"{platform_var.get().lower()}_knobs.xlsx",
        )
        if path:
            out_path_var.set(path)

    ttk.Button(frame, text="Browse Output", command=browse_out).grid(row=4, column=2, padx=8, pady=3)

    status_var = tk.StringVar(value="Ready")
    ttk.Label(frame, textvariable=status_var, foreground="#2b579a").grid(row=5, column=0, columnspan=3, sticky="w", pady=10)

    def on_export() -> None:
        platform = platform_var.get().strip().upper()
        if platform not in PLATFORM_ROOTS:
            messagebox.showerror("Error", "Please choose a valid platform.")
            return

        out_path = out_path_var.get().strip()
        if not out_path:
            messagebox.showerror("Error", "Please provide output xlsx path.")
            return

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)

        status_var.set("Exporting... please wait")
        root.update_idletasks()
        rc = run_export(platform, bios_path_var.get(), out_path)
        if rc == 0:
            status_var.set("Export completed")
            messagebox.showinfo("Done", f"Export completed:\n{out_path}")
        else:
            status_var.set(f"Export failed (code={rc})")
            messagebox.showerror("Failed", f"Export failed, exit code: {rc}")

    ttk.Button(frame, text="One-click Export", command=on_export).grid(row=6, column=0, sticky="w", pady=8)
    ttk.Button(frame, text="Close", command=root.destroy).grid(row=6, column=1, sticky="w", pady=8)

    for col in range(3):
        frame.grid_columnconfigure(col, weight=1 if col in (0, 1) else 0)

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
