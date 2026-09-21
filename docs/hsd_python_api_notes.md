# HSD integration notes

Use only the current user's approved enterprise identity, network and HSD access.
Do not request, copy or store passwords, cookies, tokens or Kerberos ticket content.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-HsdArticleFetch.ps1 -ArticleId <ARTICLE_ID> -ForceCurlDirect
```

The wrapper writes raw JSON and extracted JSON/text under `out\<ARTICLE_ID>`.
The curl route uses Windows negotiate authentication. The optional Python route
uses requests, requests-kerberos and truststore; install only the dependencies
needed by the selected route using an approved package source.

Confirm successful HTTP access and JSON article data, not an HTML access-denied
page. An authorization failure must be reported; do not disable certificate
validation or substitute another user's credentials.

`scripts\extract_hsd_article.py` can parse an already authorized local raw file
without accessing hardware. It currently extracts the first `data` record and
uses heuristic HTML stripping; a missing or incomplete result is not proof that
the original article has no relevant data.

Article/Query results, attachments and owner details are internal runtime data.
They are not included in this distribution or its Git history.
