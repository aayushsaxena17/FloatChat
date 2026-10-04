# Validation reports

Only sanitized measured evidence belongs here. Raw scanner reports, credential mappings and contaminated backups must remain outside Git and CI artifacts.

Stage 0 local unit-test evidence is `stage0-python.xml`; the gate report records static/web/scanner results. `stage0-integration.json` is produced only after actual Docker integration execution and identifies retained disposable volumes. No integration result is claimed while Docker/WSL is pending.
