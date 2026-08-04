---
description: "Use when exploring unpacked recipe source trees in OpenBMC/OpenEmbedded workspaces. Check source-index first, refresh it once when needed, and avoid repeating source-index generation in a loop if the target source is still missing."
---
# OpenBMC Source Index Usage

- Check `source-index/` first when looking for unpacked recipe sources.
- Prefer `source-index/recipes/<recipe-or-target>` over manually browsing `build/tmp/work/...` when the target source is already present.
- If the target source is missing from `source-index/`, use the `bmc-source-index` skill once to create or refresh the index.
- If `build/pn-buildlist` is missing during that refresh, provide the active image target when asked so the generator can run `bitbake -g <image>` safely.
- Do not repeat source-index generation in an infinite loop. After one refresh, if the target is still missing, switch to direct recipe metadata lookup, unpack/build guidance, or ask the user for the missing environment inputs.