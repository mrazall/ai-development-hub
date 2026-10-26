**What and why**

**How it was checked**
- [ ] `ruff` and the Python tests of the parts I touched
- [ ] `apps/web`: prettier, lint, typecheck (and a look in the browser for UI changes)
- [ ] New UI strings go through `t()` and have an English line in `apps/web/src/i18n/en.ts`

**Security**
- [ ] No secrets, tokens, hostnames or personal paths in code, tests, logs or screenshots
