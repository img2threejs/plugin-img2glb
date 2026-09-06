# plugin-img2glb

img2 plugin: image -> GLB mesh via hosted TRELLIS.

Declared capability: `{ "from": "image", "to": "glb" }`. See `SKILL.md` for usage.
The live TRELLIS call needs network access plus `gradio_client`/`huggingface_hub`;
`--probe` validates inputs and prints the emission plan with stdlib only.

## Install

```bash
img2 add img2threejs/plugin-img2glb
```

## Tests

```bash
python3 -m unittest discover -s tests
```

Tests need a harness checkout as a sibling directory named `img2-harness`, or
`IMG2_HARNESS_PATH` pointing at one. No network is used.

## Publishing to npm

CI and publishing run through the org's shared [`img2threejs/ci-workflows`](https://github.com/img2threejs/ci-workflows) reusable workflows; this repo owns only its triggers and its test command.

1. Bump the version in **both** `plugin.json` and `package.json` — the `ci` workflow's version-sync check fails the build if they disagree.
2. Update `CHANGELOG.md` if the repo has one.
3. Commit the bump.
4. Tag the commit `vX.Y.Z` (matching the new version) and push the tag. A prerelease tag (`v1.2.3-beta.1`) publishes under the matching npm dist-tag (`beta`); a stable tag publishes under `latest`.
5. The shared `npm-publish.yml` workflow re-validates the tag against `package.json` and `plugin.json`, runs this repo's tests in a job with no access to the publish credential, and runs `npm publish --provenance` using the org's `NPM_TOKEN` secret (a granular npm automation token with publish rights on the `@img2threejs` scope, configured once at the org or repo level — no per-repo trusted-publisher setup needed). Re-pushing a tag whose version is already on the registry is a no-op, not a failure.
6. Workflow references in `.github/workflows/` are pinned to a specific `ci-workflows` commit SHA, per that repo's pinning policy.
