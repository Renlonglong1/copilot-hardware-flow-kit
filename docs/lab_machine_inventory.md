# Approved local machine inventory

This distribution contains no actual lab inventory. The template has one
`UNCONFIGURED` non-operational example so the default UI can start safely.

For deployment, copy `config\lab-machine-inventory.template.json` to the ignored
`config\lab-machine-inventory.json`. Configure real assets only in that ignored
file and set the local UI profile's `machineMatching.inventoryPath` accordingly.
The workflow prompts use this same approved inventory path.

Each entry needs `id`, `platformFamily`, and `ssh.user` / `ssh.host`.
Add verified `platformAliases`, `model`, `capabilities` and `paths` as needed.
An unknown family, incompatible platform or missing evidence blocks selection.
Do not register the documentation example as an available machine.

Keep firmware/BKC inventories under `config\local\bkc-inventory.json` or an
approved internal location. Record platform, release, image path, size and SHA256.
Never substitute firmware between incompatible platforms.

The inventory is not proof of current reachability, hardware ownership or an
exclusive reservation. Confirm all three before execution. Local SQLite locks
do not coordinate other deployment instances or independent manual operations.
