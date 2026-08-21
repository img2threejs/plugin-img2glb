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
import struct
from pathlib import Path

from img2_core import paths, state

GATE = "glb-artifact"
PLUGIN = "img2glb"
EXIT = {"pass": 0, "fail": 1, "error": 2}
GLB_MAGIC = b"glTF"
GLB_HEADER_BYTES = 12


def emit(status, reasons, evidence):
    print(json.dumps({
        "kind": "img2.gate-verdict",
        "version": 1,
        "gate": GATE,
        "plugin": PLUGIN,
        "status": status,
        "reasons": reasons,
        "evidence": evidence,
    }, indent=2))
    return EXIT[status]


def expected_stem(args, workspace):
    if args.input:
        return Path(args.input).stem
    doc = state.load_state(workspace)
    generated = doc.get("plugins", {}).get(PLUGIN, {}).get("lastGenerate", {})
    stem = generated.get("stem") if isinstance(generated, dict) else None
    return stem if isinstance(stem, str) and stem else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gate_glb_artifact")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--input", default=None,
                        help="input image name whose artifact to verify; "
                             "default: the last generation recorded in workspace state")
    args = parser.parse_args(argv)
    try:
        workspace = paths.resolve_workspace(args.workspace)
    except ValueError as err:
        return emit("error", [str(err)], {})
    try:
        stem = expected_stem(args, workspace)
    except (RuntimeError, json.JSONDecodeError) as err:
        return emit("error", ["could not read workspace state: %s" % err], {})
    artifacts = Path(workspace) / ".img2" / "artifacts" / PLUGIN
    if stem is None:
        return emit("fail",
                    ["no GLB generation recorded for this workspace and no --input given"],
                    {"artifactsDir": str(artifacts)})
    glb = artifacts / (stem + ".glb")
    evidence = {"expected": str(glb)}
    if not glb.is_file():
        return emit("fail", ["artifact missing: %s" % glb], evidence)
    data = glb.read_bytes()
    evidence["bytes"] = len(data)
    if len(data) < GLB_HEADER_BYTES:
        return emit("fail", ["%s is shorter than the %d-byte GLB header" % (glb, GLB_HEADER_BYTES)], evidence)
    if data[:4] != GLB_MAGIC:
        return emit("fail", ["%s does not start with the glTF magic bytes" % glb], evidence)
    version, declared = struct.unpack_from("<II", data, 4)
    evidence["glbVersion"] = version
    evidence["declaredLength"] = declared
    if declared <= GLB_HEADER_BYTES:
        return emit("fail", ["declared GLB length %d is not greater than %d" % (declared, GLB_HEADER_BYTES)], evidence)
    return emit("pass", [], evidence)


if __name__ == "__main__":
    sys.exit(main())
