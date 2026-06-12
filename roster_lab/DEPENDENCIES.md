# Frontend Dependencies

This project uses npm dependency manifests instead of committing `node_modules`.

## Files To Commit

- `package.json`: direct dependencies and scripts.
- `package-lock.json`: exact resolved dependency tree, including transitive packages.

These two files are the npm equivalent of a pinned Python `requirements.txt` workflow.

## Install From Scratch

```bash
npm ci
```

Use `npm ci` when cloning from GitHub because it installs exactly what is recorded in `package-lock.json`.

For local dependency changes, use:

```bash
npm install <package-name>
```

Then commit the updated `package.json` and `package-lock.json`.

## Do Not Commit

- `node_modules/`
- `.next/`
- local environment files
- npm debug logs

Those are ignored by `frontend_site/.gitignore`.
