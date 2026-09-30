---
name: Bug report
about: Something in GridCast is wrong (data, metrics, site, ingest)
title: "[bug] "
labels: bug
---

**What broke and where**
(unit/page/command affected)

**Reproduce**
(exact command or URL; the smallest window that shows it)

**Expected vs actual**
(with numbers if applicable)

**Evidence**
pytest/ruff/smoke status on your branch; `git rev-parse --short HEAD`;
relevant slice of logs or the JSON keys involved.

**Data-fidelity checklist (if the bug touches numbers/dates)**
- [ ] The wrong value is traceable (source file/row or command output attached)
- [ ] It is reproducible offline (no flaky network dependence)
