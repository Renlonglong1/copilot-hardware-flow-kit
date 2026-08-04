---
name: bmc-redfish-update
description: "Update or flash an Intel OKS OpenBMC BMC over Redfish UpdateService. Use when uploading a firmware image to a BMC host or IP with an optional image path and optional credentials; defaults to debuguser/0penBmc1 and the workspace image-update symlink when no image path is supplied."
argument-hint: "BMC hostname or IP, optional image path, optional username/password"
user-invocable: true
---

# BMC Redfish Update

Use this skill when you need to push a BMC firmware image through Redfish `UpdateService/update` for day-to-day validation, bring-up, or image testing.

## Inputs

- Required: BMC hostname or IP.
- Preferred: image path.
- Optional: username and password.
- Default credentials: `debuguser` / `0penBmc1` unless the user provides other values.

## Default Image Behavior In This Workspace

- If the user provides an image path, use it exactly.
- If no image path is provided, prefer the active Redfish update payload at `build/tmp/deploy/images/intel-ast2600/image-update`.
- Only switch to a specific `OBMC-oks-*-oob.bin` path when the user explicitly asks for that artifact or passes it as the image path.
- Do not default to `image-mtd`, `*.ROM`, `*.auto.mtd`, or `*-inband.bin` for Redfish update.

See [image selection notes](./references/image-selection.md).

## Procedure

1. Resolve the target BMC hostname or IP.
2. Resolve the image path and verify that the file exists.
3. Use the helper script [redfish-bmc-update.sh](./scripts/redfish-bmc-update.sh).
4. Prefer `curl -u` authentication instead of embedding credentials in the URL.
5. Preserve `--noproxy` for the BMC host and use `Content-Type: application/octet-stream`.
6. Report the exact BMC target, image path, and whether default credentials were used.

## Helper Script Usage

```bash
./copilot/skills/bmc-redfish-update/scripts/redfish-bmc-update.sh --bmc oks-bmc-818027
./copilot/skills/bmc-redfish-update/scripts/redfish-bmc-update.sh --bmc oks-bmc-818027 --image ./OBMC-oks-example-oob.bin
./copilot/skills/bmc-redfish-update/scripts/redfish-bmc-update.sh --bmc 10.0.0.25 --image build/tmp/deploy/images/intel-ast2600/image-update --user admin --password secret
```

## Equivalent Curl Pattern

```bash
curl --noproxy "$BMC_HOST" -k --fail-with-body -X POST \
  -u "$BMC_USER:$BMC_PASS" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$IMAGE_PATH" \
  "https://$BMC_HOST/redfish/v1/UpdateService/update"
```

## Failure Handling

- If the upload fails, surface the HTTP response body when available.
- Re-check that the image path points to a Redfish-compatible update payload.
- Re-check DNS reachability or proxy bypass when the BMC host is a lab hostname.
- If the user did not provide credentials, state that the default `debuguser` / `0penBmc1` pair was used.