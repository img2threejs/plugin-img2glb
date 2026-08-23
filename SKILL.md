---
name: img2-img2glb
description: "Converts a single image into a GLB 3D mesh using a hosted TRELLIS reconstruction service. Use when the user asks to turn an image into a GLB/3D mesh file."
---

# img2glb

Turns one reference image into a GLB 3D mesh by calling a hosted TRELLIS Space
(default `trellis-community/TRELLIS`). TRELLIS itself is CUDA-only and never runs
locally; the Space runs it on the provider's hardware, so an Apple Silicon machine
still gets TRELLIS output.

Honest capability note: the **live call needs network access** plus the third-party
Python packages `gradio_client` and `huggingface_hub` (imported lazily, only on the
live path), and optionally a Hugging Face token for ZeroGPU quota. The **`--probe`
mode is pure stdlib and needs no network** — it validates the input image and prints
the emission plan, and is the path the automated tests exercise. A green probe proves
the plumbing, not a generated mesh.

## Usage

Run every command from the user's project directory and pass that directory as
`--workspace`. Never point `--workspace` at this skill directory or any checkout.
`$SKILL_DIR` below is the directory containing this SKILL.md.

Probe (offline validation + plan):

```bash
python3 "$SKILL_DIR/tools/img2glb.py" --probe --image <path/to/image> --workspace "$PWD"
```

Prints an `img2.probe` envelope on stdout and exits 0; exits 2 when the input image
is missing, unreadable, or empty.

Live generation (network + `gradio_client`/`huggingface_hub`):

```bash
python3 "$SKILL_DIR/tools/img2glb.py" --image <path/to/image> --workspace "$PWD" \
  [--space trellis-community/TRELLIS] [--seed 0] [--mesh-simplify 0.95] \
  [--texture-size 512] [--hf-token TOKEN]
```

Gate (offline, verifies the emitted artifact):

```bash
python3 "$SKILL_DIR/tools/gate_glb_artifact.py" --workspace "$PWD" [--input <path/to/image>]
```

Without `--input` the gate verifies the last generation recorded in workspace state —
that is how `gates.json` runs it through `img2_core.gate_runner`.

## Outputs

All artifacts land under the user's workspace, never in a checkout:

- `<workspace>/.img2/artifacts/img2glb/<stem>.glb` — the mesh (Three.js loads it via GLTFLoader)
- `<workspace>/.img2/artifacts/img2glb/<stem>.report.json` — stdlib GLB inspection
  (mesh/material counts, `extensionsRequired`, Draco/meshopt compression flag)

State is recorded under the plugin's own subtree in `<workspace>/.img2/state.json`
(`lastProbe`, `lastGenerate`).

## Caveats

- The generated mesh is a generative proxy, not ground truth — a hallucinated back
  side is exactly what a confident-but-wrong metric would optimise toward. Score it
  against the original reference image before trusting it.
- A GLB that declares Draco/meshopt compression needs DRACOLoader in Three.js and is
  unreadable by pure-Python consumers; the report flags this.
- In `steps.json`, `{image}` marks the caller-supplied input path; the harness
  substitutes only `{workspace}` and `{plugin_dir}`.
- The OBJ export and multi-view generation of the original `generate_reference_mesh.py`
  integration are out of scope here: this plugin's declared capability is
  `image -> glb` only.
