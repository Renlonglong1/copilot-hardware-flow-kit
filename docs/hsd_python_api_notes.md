# HSDES Python API Notes

Use this note when the user asks Copilot to search HSD/HSDES, extract article fields, summarize HSD issues, run HSD query IDs, or write Python code against the HSDES REST API.

## Local Setup Validated on This PC

```text
Python: 3.14.5
Installed modules: requests, requests-kerberos, certifi, truststore
Working auth path: Kerberos through requests_kerberos.HTTPKerberosAuth()
Working TLS path: truststore.inject_into_ssl() to use the Windows enterprise certificate store
```

Do not ask for or store passwords, cookies, SSO tokens, service tokens, or Kerberos ticket contents. Use the user's existing Windows/Kerberos login context.

If dependencies are missing, install with the Intel HTTP proxy:

```powershell
py -m pip --proxy http://proxy-dmz.intel.com:911 install requests requests-kerberos certifi truststore
```

The HTTPS proxy port may fail with SSL EOF; the HTTP proxy port `911` worked for Python packages.

## Validated Fetch Wrapper

Use the wrapper first for article lookup and field extraction:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976
```

Outputs are written under `out\<articleId>\` by default:

```text
out\<articleId>\hsd_<articleId>_raw.json
out\<articleId>\hsd_<articleId>_extracted.json
out\<articleId>\hsd_<articleId>_extracted.txt
```

If Python Kerberos fetch is blocked by a web gateway, force the direct curl path:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId 14027366976 -ForceCurlDirect
```

## REST API Base URLs

```text
Production API: https://hsdes-api.intel.com/rest
Pre-production API: https://hsdes-api-pre.intel.com/rest
Interactive HSD UI: https://hsdes.intel.com/appstore/article_legacy/#/<articleId>
API documentation: https://hsdes.intel.com/rest/doc/
```

The browser UI URL is not enough for automation because it is a single-page app and article data is fetched by authenticated API calls. Prefer `hsdes-api.intel.com/rest/...`.

## Python Boilerplate

```python
import truststore
truststore.inject_into_ssl()

import requests
from requests_kerberos import HTTPKerberosAuth

HEADERS = {"Content-type": "application/json"}
AUTH = HTTPKerberosAuth()
```

## Get an Article by ID

```python
article_id = "14027920810"
url = f"https://hsdes-api.intel.com/rest/article/{article_id}"

r = requests.get(url, auth=AUTH, headers=HEADERS, timeout=30)
r.raise_for_status()

rows = r.json()["data"]
row = rows[0]
print(row["id"], row["title"], row["status"])
```

Observed shape: `response.json()["data"]` is a list. For article `14027920810`, the list had one row and about 403 fields.

## Access-Denied / Proxy Diagnosis

Validated on 2026-06-23: Python `requests` through the default network path returned HTTP `403` with a generic HTML `Access Denied` page for both a known-good article and the target article. This was not an article-specific permission issue.

The working fallback was Windows `curl.exe` with Kerberos and proxy bypass:

```powershell
curl.exe --noproxy "*" --negotiate -u : -L -s -D headers.txt https://hsdes-api.intel.com/rest/article/<articleId> -o hsd_<articleId>_raw.json
```

Use `klist` to confirm there is an active Kerberos ticket. Do not ask for or store passwords, cookies, SSO tokens, service tokens, or Kerberos ticket contents.

## Execute a Saved Query ID

```python
query_id = "16010897558"
url = f"https://hsdes-api.intel.com/rest/query/execution/{query_id}"

r = requests.get(url, auth=AUTH, headers=HEADERS, timeout=60)
r.raise_for_status()

for row in r.json()["data"]:
    print(row["id"])
```

## Execute EQL

Keep EQL targeted to a tenant/subject for performance.

```python
url = "https://hsdes-api.intel.com/rest/query/execution/eql?start_at=1"
payload = {
    "eql": "select id,description where discovery.issue.id = 123"
}

r = requests.post(url, json=payload, auth=AUTH, headers=HEADERS, timeout=60)
r.raise_for_status()

for row in r.json()["data"]:
    print(row["id"])
```

## Create or Update Articles

Use pre-production unless the user explicitly asks to change production data.

Create an article:

```python
url = "https://hsdes-api-pre.intel.com/rest/article"
payload = {
    "subject": "issue",
    "tenant": "discovery",
    "fieldValues": [
        {"title": "Testing ES Python API sample"},
        {"send_mail": "false"},
        {"owner": "owner_idsid"}
    ]
}

r = requests.post(url, json=payload, auth=AUTH, headers=HEADERS, timeout=60)
r.raise_for_status()
print(r.json()["new_id"])
```

Update an article:

```python
article_id = "1307389436"
url = f"https://hsdes-api-pre.intel.com/rest/article/{article_id}"
payload = {
    "tenant": "discovery",
    "subject": "issue",
    "fieldValues": [
        {"title": "testing from python API"},
        {"send_mail": "false"}
    ]
}

r = requests.put(url, json=payload, auth=AUTH, headers=HEADERS, timeout=60)
r.raise_for_status()
print(r.text)
```

Create a comment by posting a `comments` subject with `parent_id`:

```python
url = "https://hsdes-api-pre.intel.com/rest/article"
payload = {
    "subject": "comments",
    "tenant": "discovery",
    "fieldValues": [
        {"description": "Testing ES Python API sample comment"},
        {"parent_id": 1308119657},
        {"send_mail": "false"}
    ]
}
```

## Attachments

List article attachments:

```python
article_id = "1234567"
tenant = "server_platf_ae"
url = f"https://hsdes-api.intel.com/rest/article/{article_id}/children"
params = {"tenant": tenant, "child_subject": "attachment"}

r = requests.get(url, params=params, auth=AUTH, headers=HEADERS, timeout=30)
r.raise_for_status()
attachments = r.json()["data"]
```

Download an attachment:

```python
file_id = attachments[0]["id"]
file_name = attachments[0]["title"]
url = f"https://hsdes-api.intel.com/rest/binary/{file_id}"

r = requests.get(url, auth=AUTH, timeout=60)
r.raise_for_status()

with open(file_name, "wb") as f:
    f.write(r.content)
```

Upload an attachment:

```python
article_id = "1305489307"
url = f"https://hsdes-pre.intel.com/rest/binary/upload/{article_id}"
payload = {
    "file_name": file_name,
    "title": file_description,
    "send_mail": "false"
}
files = {file_name: file_data}

r = requests.post(url, data=payload, files=files, auth=AUTH, timeout=60)
r.raise_for_status()
print(r.json().get("newID"))
```

## Field Discovery and Extraction Pattern

HSD fields may be unqualified, such as `description`, `status`, `comments`, or tenant/subject-qualified, such as `server_platf_ae.bug.ext_cust_blog_hist`.

Use substring matching to find exact field names before assuming a key:

```python
for needle in ["description", "status", "ext_cust", "blog", "hist", "comment"]:
    matches = [k for k in sorted(row) if needle.lower() in k.lower()]
    print(needle, matches)
```

Common fields from article `14027920810`:

```text
description
status
comments
server_platf_ae.bug.ext_cust_blog_hist
server_platf_ae.bug.ext_cust_blog_hist_rich
server_platf_ae.bug.ext_cust_blog
server_platf_ae.bug.ext_cust_blog_rich
```

## Validated Example: Article 14027920810

Basic fields:

```text
id: 14027920810
title: 某客户出现微码已知问题IFU问题，咨询是否可以只升级微码进行解决
tenant: server_platf_ae
subject: bug
status: open
owner: rongyaow
family: Whitley Platforms
component: platform.bios
reason: awaiting_customer
submitted_date: 2026-05-26 15:21:35.547
updated_date: 2026-06-04 14:16:52.33
```

Requested extraction fields for this article:

```text
Description: customer asks whether IFU known issue can be resolved by microcode/MCU upgrade only, or whether full BKC upgrade is required; debug request details are mostly blank.
Overview status: open
ext_cust_blog_hist: actual key is server_platf_ae.bug.ext_cust_blog_hist
Comments: system routing comments plus one sighting reference to Oracle/Alibaba/Seer/Whitley IFU Internal Parity Error sightings.
```

Summary of the article:

```text
Customer reports batch IFU failures on Whitley systems and asks whether upgrading MCU/microcode is sufficient. Intel recommendation in external customer blog history is to upgrade at least to MR5 MCU for the known IFU parity fix, collect RC + MCU versions from affected systems, confirm whether all failures occur below MR5, and share an MCU upgrade validation plan if needed. Article remains open and awaiting customer.
```

## Microcode Guidance Captured From Article 14027920810

Linux hot microcode update guidance shared in the customer communication:

```bash
cp <family-model-stepping microcode image> /lib/firmware/intel-ucode/
echo 1 > /sys/devices/system/cpu/microcode/reload
dmesg
rdmsr 0x8b
```

Use `dmesg` and `rdmsr 0x8b` to check update status and current microcode version.

## Validated Example: Article 14027366976

Basic fields:

```text
id: 14027366976
title: [MEM] GNR-SP HCC Support 2+2 DIMM Population
tenant: server_platf_ae
subject: bug
status: complete
owner: rongyaow
family: Birch Stream Platform
component: platform.bios
submitted_date: 2026-03-12 15:36:53.187
updated_date: 2026-03-25 13:24:22.34
bug.verified_date: 2026-03-25 13:24:11.0
server_platf_ae.bug.ext_priority: Low
server_platf_ae.bug.current_owner_org: pse_china
bug.fix_description: MagInfra GNR-SP HCC 2-DIMM CVILS PORed
```

Issue summary:

```text
Customer MagInfra requested/confirmed GNR-SP HCC support for 2+2 DIMM population using CPU SKUs 6521P, 6511P, and 6515P with Samsung DDR5-6400 32GB/64GB AVL parts. Customer also clarified that both PB and EB die process nodes need support and asked which two slots are recommended for 2DPC. Intel approved the request, uploaded the CVILS agreement, and recommended populating CH0/CH4 (C0D0/C4D0 in the customer diagram).
```

Initial handling hypothesis:

```text
This article is a memory population support / AVL / CVILS POR confirmation rather than a classic failure-debug article. If a similar platform later shows boot, memory inventory, stress, MLC, or Stream issues, first verify DIMM topology uses CH0/CH4 = C0D0/C4D0, DIMM PN minor version and PB/EB die-node coverage match the approved scope, and BIOS/MRC support for GNR-SP HCC 2-DIMM population is present.
```
