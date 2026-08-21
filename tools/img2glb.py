#!/usr/bin/env python3
import os, sys
root = os.environ.get("IMG2_HOME")
if root: sys.path.insert(0, os.path.join(root, "harness"))
else:
    try: import _img2_local; sys.path.insert(0, _img2_local.CORE)
    except ImportError: sys.exit("img2: core not linked - run `img2 sync`")
from img2_core import require_core_api
require_core_api(1)

import argparse
import json
import shutil
import struct
from datetime import datetime, timezone
from pathlib import Path

from img2_core import paths, state

PLUGIN = "img2glb"
PROBE_KIND = "img2.probe"
PROBE_VERSION = 1
DEFAULT_SPACE = "trellis-community/TRELLIS"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="img2glb",
        description="Turn an image into a GLB 3D mesh via the hosted TRELLIS space.",
    )
    p.add_argument("--image", required=True, type=Path)
    p.add_argument("--workspace", default=None)
    p.add_argument("--probe", action="store_true",
                   help="validate the input and print the emission plan; no network, stdlib only")
    p.add_argument("--space", default=DEFAULT_SPACE)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--mesh-simplify", type=float, default=0.95,
                   help="TRELLIS simplify ratio, demo range 0.9-0.98; in the reference demo this is "
                        "the fraction of triangles REMOVED, so verify against the reported count")
    p.add_argument("--texture-size", type=int, default=512,
                   help="kept small on purpose: geometry is what is being scored")
    p.add_argument("--hf-token", default=None)
    return p.parse_args(argv)


def artifacts_dir(workspace):
    return Path(workspace) / ".img2" / "artifacts" / PLUGIN


def artifact_plan(image):
    stem = Path(image).stem
    return stem, [
        ".img2/artifacts/%s/%s.glb" % (PLUGIN, stem),
        ".img2/artifacts/%s/%s.report.json" % (PLUGIN, stem),
    ]


def input_problems(image):
    path = Path(image)
    if not path.is_file():
        return ["input image not found: %s" % path]
    try:
        with open(path, "rb") as fh:
            first = fh.read(1)
    except OSError as err:
        return ["input image not readable: %s" % err]
    if not first:
        return ["input image is empty: %s" % path]
    return []


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def record(workspace, key, payload):
    doc = state.load_state(workspace)
    state.plugin_state(doc, PLUGIN)[key] = payload
    state.save_state(workspace, doc)


def probe(args, workspace):
    problems = input_problems(args.image)
    if problems:
        for problem in problems:
            print("img2glb: %s" % problem, file=sys.stderr)
        return 2
    stem, would_emit = artifact_plan(args.image)
    resolved = str(Path(args.image).resolve())
    record(workspace, "lastProbe", {
        "input": resolved,
        "stem": stem,
        "wouldEmit": would_emit,
        "at": now_utc(),
    })
    print(json.dumps({
        "kind": PROBE_KIND,
        "version": PROBE_VERSION,
        "plugin": PLUGIN,
        "input": resolved,
        "wouldEmit": would_emit,
    }, indent=2))
    return 0


def generate(args, glb_path):
    try:
        from gradio_client import Client, handle_file
        from huggingface_hub import get_token
    except ImportError as err:
        sys.exit(
            "img2glb: the live TRELLIS call needs the third-party packages gradio_client and "
            "huggingface_hub (%s); install them for this interpreter, or run --probe, which "
            "validates without them" % err
        )

    # gradio_client names the argument `token`, not `hf_token`, and rejects the other spelling;
    # falling back to the stored `hf auth login` token keeps ZeroGPU quota from silently running
    # anonymous.
    token = args.hf_token or get_token()
    client = Client(args.space, token=token, verbose=False)
    print("auth       : %s" % ("token" if token else "anonymous"), file=sys.stderr)
    print("space      : %s" % args.space, file=sys.stderr)

    # TRELLIS creates its per-session scratch directory in a `demo.load` handler, which fires for
    # browsers but not API clients; skipping /start_session makes every later step fail with a bare
    # server-side FileNotFoundError. The session hash is per-Client, so it must run on this instance.
    client.predict(api_name="/start_session")
    result = client.predict(
        image=handle_file(str(args.image)),
        multiimages=[],
        seed=args.seed,
        ss_guidance_strength=7.5,
        ss_sampling_steps=12,
        slat_guidance_strength=3.0,
        slat_sampling_steps=12,
        multiimage_algo="stochastic",
        mesh_simplify=args.mesh_simplify,
        texture_size=args.texture_size,
        api_name="/generate_and_extract_glb",
    )
    glb_source = None
    for item in result:
        candidate = item.get("video") if isinstance(item, dict) else item
        if isinstance(candidate, str) and candidate.lower().endswith(".glb"):
            glb_source = candidate
    if glb_source is None:
        sys.exit("img2glb: no .glb in TRELLIS response: %r" % (result,))
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(glb_source, glb_path)


def inspect_glb(glb_path):
    data = Path(glb_path).read_bytes()
    if len(data) < 20:
        sys.exit("img2glb: %s is shorter than a GLB header plus one chunk header" % glb_path)
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        sys.exit("img2glb: %s is not a GLB (bad magic)" % glb_path)
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A:
        sys.exit("img2glb: first GLB chunk in %s is not JSON" % glb_path)
    gltf = json.loads(data[20:20 + chunk_length])
    required = gltf.get("extensionsRequired", [])
    return {
        "extensionsRequired": required,
        "compressed": any("draco" in e.lower() or "meshopt" in e.lower() for e in required),
        "meshes": len(gltf.get("meshes", [])),
        "materials": len(gltf.get("materials", [])),
    }


def run_live(args, workspace):
    problems = input_problems(args.image)
    if problems:
        for problem in problems:
            print("img2glb: %s" % problem, file=sys.stderr)
        return 2
    stem, emitted = artifact_plan(args.image)
    out_dir = artifacts_dir(workspace)
    glb_path = out_dir / (stem + ".glb")
    generate(args, glb_path)
    info = inspect_glb(glb_path)
    resolved = str(Path(args.image).resolve())
    report = {
        "plugin": PLUGIN,
        "input": resolved,
        "glb": str(glb_path),
        **info,
    }
    (out_dir / (stem + ".report.json")).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    record(workspace, "lastGenerate", {
        "input": resolved,
        "stem": stem,
        "artifacts": emitted,
        "space": args.space,
        "seed": args.seed,
        "at": now_utc(),
    })
    print(json.dumps(report, indent=2))
    if info["compressed"]:
        print("WARNING: GLB declares compression in extensionsRequired; Three.js needs DRACOLoader "
              "and pure-Python consumers cannot read it.", file=sys.stderr)
    print("NOTE: this mesh is a generative PROXY, not ground truth. Score it against the original "
          "reference image before trusting it as a scoring reference.", file=sys.stderr)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        workspace = paths.resolve_workspace(args.workspace)
    except ValueError as err:
        print("img2glb: %s" % err, file=sys.stderr)
        return 2
    if args.probe:
        return probe(args, workspace)
    return run_live(args, workspace)


if __name__ == "__main__":
    sys.exit(main())
