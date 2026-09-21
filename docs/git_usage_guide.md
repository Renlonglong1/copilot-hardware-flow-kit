# Git handover workflow

This distribution is an independent root branch, not a mergeable descendant of
the old `main`. Clone it separately using the branch command in `README.md`.
Keep the repository private and use approved individual identities.

Develop in a new topic branch. Review each path before staging, keep actual
deployment settings ignored, and submit changes for review. Deployment machines
pull approved commits and do not develop directly against attached hardware.

Record the actual remote branch and commit at acceptance. A local commit alone
does not prove upload succeeded. Roll back by deploying an approved known-good
version and compatible data backup, not by force-resetting local user data.

Internal material in old branches remains a separate administrator-owned cleanup
issue. Do not force-push or delete those branches as part of this handover.
