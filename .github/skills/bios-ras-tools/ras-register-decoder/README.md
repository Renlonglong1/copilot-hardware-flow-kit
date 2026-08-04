# RAS Register Decoder

Local web application for browsing and decoding Intel RAS register definitions.
The package includes the following platforms:

- BHS / Granite Rapids
- OKS / Diamond Rapids

## Start

1. Run `start.bat`.
2. The browser opens at `http://localhost:18080/`.
3. Select the target platform from the **Platform** selector.
4. Search for a register by name or address, enter a hexadecimal value, then select **Decode**.

The platform can also be selected directly in the URL:

- `http://localhost:18080/?platform=BHS`
- `http://localhost:18080/?platform=OKS`

Keep the command window opened by `start.bat` running while using the application. Closing it stops the local web server.

## Included Data

- `app/data/BHS/registers.json`: BHS register database.
- `app/data/OKS/registers.json`: OKS EDS/DDTT-backed register database, including MCA bank registers and EDS field definitions.

The application is self-contained and does not require Python or external package installation to run.
