---
name: generic-open-hsd
description: 'Open Intel HSD (Hardware Security Design) tickets automatically in the web browser by ticket number across Windows, Linux, and macOS. Use when you need to quickly view an HSD article or issue (e.g., "open HSD 14026650639"). Automatically launches the ticket in your default browser.'
argument-hint: 'HSD ticket number (e.g., 14026650639)'
user-invocable: true
---

# Open HSD Tickets

## When to Use
- Quickly open HSD tickets in your browser
- Works on Windows, Linux, and macOS
- Automatically launches in your default browser

## How to Use

### Via Slash Command
```
/generic-open-hsd 14026650639
```

### Inline in Chat
```
open HSD 14026650639
open HSD ticket #14026650639
```

## Platform Support
- **Windows**: Uses PowerShell `Start-Process` ([open-hsd.ps1](./scripts/open-hsd.ps1))
- **Linux**: Uses `xdg-open` ([open-hsd.sh](./scripts/open-hsd.sh))
- **macOS**: Uses `open` command ([open-hsd.sh](./scripts/open-hsd.sh))

## How It Works

The skill constructs the HSD URL and opens it in your default browser:
```
https://hsdes.intel.com/appstore/article-one/#/{TICKET_NUMBER}
```

Example: ticket `14026650639` opens in your browser automatically.

## Notes
- Requires internet access to Intel's HSD system
- You must have appropriate access permissions to view the ticket
- Scripts automatically detect your OS and use the appropriate browser launcher
