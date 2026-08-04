---
name: sysdbg-setup-linux-build-env
description: "Set up a Linux build environment for Intel UEFI/BIOS firmware compilation. Use when: setting up dt user, installing edkrepo, installing NASM/GCC, building LLVM/CLANG from source, configuring python for BIOS build, installing ModularFIT/FIT tool requirements, preparing BirchStream/OakStream/EagleStream build machine."
argument-hint: "Optional: distro (ubuntu, centos) and project (BirchStream, OakStream, EagleStream)"
---

# Linux Build Environment Setup (Intel UEFI/BIOS Firmware)

## When to Use

- **Setting up a new Linux machine** for Intel BIOS/UEFI firmware compilation
- **Installing edkrepo** and CrTools for EDK II development
- **Building LLVM/CLANG from source** for firmware compilation
- **Configuring Python environment** for FIT/ModularFIT tools
- **Preparing BirchStream, OakStream, or EagleStream** build environments

## Overview

This skill covers the complete workflow to prepare a Linux machine for Intel UEFI/BIOS firmware builds, from user setup through compiler installation and Python dependency configuration.

## Step-by-Step Procedure

### 1. Set Up User with `dt` (DevTool)

Use `dt` to configure the build user account:

```bash
# Download dt from:
# https://gfx-assets.intel.com/artifactory/gfx-build-assets/build-tools/devtool-go/latest/artifacts/linux64/dt
chmod +x dt
./dt setup
```

### 2. Install CrToolsSetup (edkrepo)

Download and install CrToolsSetup to get the `edkrepo` command:

```bash
# Download from:
# https://ubit-artifactory-or.intel.com/artifactory/comanche-ridge-tools-local/cr-tools/CrToolsSetup-3.3.0.0.tar.gz
# Release notes: https://intel.sharepoint.com/sites/intel-uefi-continuous-integration-center/SitePages/EdkRepo-v3.3.0-Release-Notes.aspx

tar xvf CrToolsSetup-3.3.0.0.tar.gz
python install.py --user root
```

### 3. Install NASM, GCC, and Required Packages

Install compiler toolchain and build dependencies.

**CentOS/RHEL:**
```bash
yum install nasm gcc gcc-c++ libarchive libuuid libuuid-devel cmake git
```

> For NASM on CentOS 9 Stream:
> - Package: https://centos.pkgs.org/9-stream/centos-crb-x86_64/nasm-2.15.03-7.el9.x86_64.rpm.html
> - Direct RPM: https://mirror.stream.centos.org/9-stream/CRB/x86_64/os/Packages/nasm-2.15.03-7.el9.x86_64.rpm
> - Or build from source: https://www.nasm.us/pub/nasm/releasebuilds/

**Ubuntu/Debian:**
```bash
apt update
apt install git make cmake gcc uuid uuid-dev nasm
```

### 4. Install LLVM/CLANG (Build from Source)

> **Important**: Check the OTC wiki for the required LLVM version for your project. Using a version that is too old or too new may cause compilation issues.

```bash
# Example: LLVM 12.0.0
# Latest releases: https://github.com/llvm/llvm-project/releases/tag/llvmorg-20.1.0
wget https://github.com/llvm/llvm-project/archive/refs/tags/llvmorg-12.0.0.tar.gz
tar xvf llvmorg-12.0.0.tar.gz
cd llvm-project-llvmorg-12.0.0

cmake -S llvm -B build \
  -DLLVM_ENABLE_PROJECTS="clang;lld" \
  -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Release

cd build
make all -j48
make install

# Verify installation
clang -v
lld-link --version
```

### 5. Install Project-Specific Python Version

Each project may require a specific Python version. Install the required version per project documentation before proceeding.

### 6. Install Python Requirements (FIT/ModularFIT Tools)

Install the Python dependencies for FIT tools using the project's `requirements_linux.txt`:

```bash
cd <path-to-project>/Intel/Build/<ProjectPkg>/FITm_GNRSRF_IBL/ModularFIT_cmd_5.9.14

python -m pip install \
  -i https://mirrors.aliyun.com/pypi/simple \
  --proxy http://child-prc.intel.com:913 \
  -r requirements_linux.txt
```

> Replace `<path-to-project>` and `<ProjectPkg>` with your actual project path (e.g., `BirchStreamRp/Intel/Build/BirchStreamRpPkg`).

## Troubleshooting

| Issue | Solution |
|-------|----------|
| CLANG version mismatch | Check OTC wiki for the required LLVM version for your specific project |
| NASM not found on CentOS 9 | Install from CRB repo or build from source (see Step 3 links) |
| `edkrepo` command not found | Verify `install.py --user root` completed successfully; re-run if needed |
| pip install fails (proxy error) | Confirm proxy `http://child-prc.intel.com:913` is reachable from your machine |
| `make all` too slow | Increase parallel jobs: `make all -j$(nproc)` |

## Next Steps

After environment setup:
1. **Clone the firmware repo** using `edkrepo clone`
2. **Set up build variables** per project build scripts
3. **Trigger a build** (e.g., `python build.py` or project-specific script)
4. **Verify build output** in the project's `Build/` directory

---

**Status**: ✅ Ready to use
**Last Updated**: 2026-05-08
