# Agent session memory (Cursor / automation)

This file is for **future sessions** and humans: repo layout, what changed in working sessions, and operational notes. Update it when major integration or deploy behavior changes.

---

## Repository layout (critical)

- **`/Users/mac/naturepath` is not a git repository.** Tooling placed only here (e.g. `.github/`, root `package.json`, `.husky/`) is **not** pushed with either app until copied into a repo.
- **Two separate Git remotes:**
  - **Frontend:** `frontend/` → `https://github.com/dagogodboss/naturepath.git`
  - **Backend:** `backend/` → `https://github.com/dagogodboss/naturepath-backend.git`
- **`backend/sdk/`** is **not** its own repo; it ships with **naturepath-backend**.

---

## npm SDK (`natural-path-sdk`)

- **Published name:** `natural-path-sdk` (**unscoped**). The original `@natural-path/sdk` failed with **“Scope not found”** because the `@natural-path` org did not exist on npm.
- **Registry:** [npmjs.com/package/natural-path-sdk](https://www.npmjs.com/package/natural-path-sdk) — `1.0.0` published successfully.
- **Imports:** All code uses `import … from 'natural-path-sdk'` (not `@natural-path/sdk`).
- **Publish locally:** `backend/scripts/publish-sdk-to-npm.sh` (requires `NODE_AUTH_TOKEN` or `NPM_TOKEN` in env; uses a temp userconfig — never commit tokens).
- **GitHub Actions:** Root-level `.github/workflows/publish-sdk.yml` publishes from `backend/sdk` on tag `sdk/v*` or `workflow_dispatch`. **Copy this into `naturepath-backend/.github/workflows/`** if CI should run from that repo (parent `.github` is not tracked today).
- **Security:** Any npm token pasted in chat must be **revoked** on npm and replaced; never store tokens in the repo.

---

## Frontend (`naturepath` repo)

- **Dependency:** `"natural-path-sdk": "^1.0.0"` from the **npm registry** (not `file:../backend/sdk`).
- **Vite:** The dev alias that pointed `natural-path-sdk` → `../backend/sdk/src/index.ts` was **removed** so the app resolves the **installed** package (`node_modules/…/dist`), matching production consumers.
- **Lockfile:** After switching to the registry, `package-lock.json` should resolve `natural-path-sdk` to `https://registry.npmjs.org/natural-path-sdk/-/natural-path-sdk-1.0.0.tgz` (regenerate with a clean `npm install` if it still showed `link: true` to `../backend/sdk`).
- **Local SDK iteration:** Use `npm link` or temporarily restore `file:` + Vite alias; document in `backend/sdk/README.md`.

---

## Backend / AWS (operational notes from this project)

- **ECS:** Cluster `natural-path-prod`, service `natural-path-service`, task definition `natural-path:4`; API image `…/natural-path-api:latest` on port **8001**; sidecar-style task also runs Mongo + Redis in the described setup.
- **ALB (example):** `http://natural-path-alb-1531242156.us-east-1.elb.amazonaws.com` — health: `GET /api/health`.
- **Frontend static:** Bucket `natural-path-frontend-371416036862` (private; typically fronted by CloudFront). Production builds use `VITE_NATURAL_PATH_API_URL` pointing at the real API URL.
- **Deploy workflow:** `.github/workflows/deploy-backend-ecs.yml` (ECR build/push + `ecs update-service --force-new-deployment`). **Also copy into backend repo** if using GitHub Actions from `naturepath-backend`.
- **Secrets for Actions:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or OIDC); `NPM_TOKEN` for SDK publish.
- **Local Docker for ECR builds:** Docs recommend **Colima** on macOS (`colima start` before `docker build` / `docker login` / `docker push`). See `backend/docs/DEPLOYMENT_AWS.md`.
- **`DEPLOYMENT_AWS.md`:** Updated with Colima, CI section, Husky note (root `npm install` sets hooks only if `.git` exists at that path).

---

## Husky / git hooks

- Root `package.json` + `.husky/pre-push` live under **parent** `naturepath/` (no `.git`). They only apply if git is initialized at that level or hooks are copied elsewhere. **Pre-push does not deploy**; deploy-after-push is intended via **GitHub Actions**.

---

## Product / code context (from transcripts referenced in session)

- **RBAC:** Casbin policies; `owner` inherits `admin`; practitioner narrowed vs earlier “practitioner = admin”; admin RBAC UI; audit logging.
- **Booking:** Auto-assign practitioner (no customer picker); `GET /api/booking/service-slots`; round-robin + Mongo cursor.
- **SDK:** Public API surface must re-export everything from `sdk/src/index.ts` (Vite may resolve source in monorepo dev).

---

## Follow-ups (optional)

- [ ] Copy `.github/workflows/*.yml` into **`naturepath-backend`** (and frontend repo when adding SPA deploy).
- [ ] Add `backend/.gitignore` entries for `.DS_Store`, `*.log` if logs were accidentally staged.
- [ ] Align `backend/sdk/package.json` `repository` URL if `dagogodboss/naturepath` is not the canonical monorepo URL.
- [ ] CloudFront + strict `CORS_ALLOWED_ORIGINS` when the public SPA domain is final.

---

## How to update this file

After significant deploy, SDK, or repo-structure changes, append a short dated subsection or edit the relevant section so the next session does not rely on chat history alone.

*Last updated: session documenting SDK npm publish, frontend switch to registry, split-repo layout, AWS/Colima/CI notes, and follow-ups.*
