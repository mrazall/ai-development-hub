# Image sources

- `social-preview.html` → `../social-preview.png` (1280×640): open it in Chromium at 1280×640 and take a
  screenshot (`node shot.mjs`-style Playwright call, `deviceScaleFactor: 1`).
- `../workspace.png`, `../chats.png`, `../knowledge.png`, `../demo.gif`: captured from `./scripts/quickstart.sh --demo`
  (mock engines, demo vault), English UI, dark theme.
- `../repo.png`, `../instructions.png`, `../efficiency.png`: `shots/shots.spec.ts` with the made-up data in
  `shots/data.mjs` (every API answer is mocked, so no hub data appears). Copy both files into `apps/web/e2e/shots/`,
  start the dev panel and run `SHOTS_OUT=<dir> npx playwright test e2e/shots/shots.spec.ts --project=desktop`.
