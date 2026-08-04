# Image Selection Notes

This workspace uses Intel OKS OpenBMC defaults for Redfish update payload selection.

- Preferred default payload: `build/tmp/deploy/images/intel-ast2600/image-update`
- The `image-update` symlink is the default answer for the latest active Redfish firmware payload in this repo.
- A specific `OBMC-oks-*-oob.bin` file is also valid for out-of-band update when the user explicitly provides or requests that file.
- Do not default to `image-mtd`, `*.auto.mtd`, `*.ROM`, or `*-inband.bin` for a standard Redfish upload flow.

If the user asks for the currently active artifact without providing a path, prefer the `image-update` symlink instead of sorting filenames manually.
