import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HARNESS = Path(os.environ.get("IMG2_HARNESS_PATH", PLUGIN_DIR.parent / "img2-harness")).resolve()
TOOL = PLUGIN_DIR / "tools" / "img2glb.py"
GATE = PLUGIN_DIR / "tools" / "gate_glb_artifact.py"


def write_png(path):
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def write_minimal_glb(path, declared_length=None):
    body = b"\x00" * 8
    total = 12 + len(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    declared = total if declared_length is None else declared_length
    path.write_bytes(b"glTF" + struct.pack("<II", 2, declared) + body)


class PluginCase(unittest.TestCase):
    def setUp(self):
        if not HARNESS.is_dir():
            raise AssertionError(
                "harness checkout not found at %s; set IMG2_HARNESS_PATH" % HARNESS
            )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.home = base / "img2home"
        self.home.mkdir()
        (self.home / "harness").symlink_to(HARNESS)
        self.workspace = base / "ws"
        self.workspace.mkdir()
        self.image = self.workspace / "photo.png"
        write_png(self.image)
        self.env = dict(
            os.environ,
            IMG2_HOME=str(self.home),
            PYTHONPATH=str(self.home / "harness"),
        )
        self.env.pop("IMG2THREEJS_HOME", None)

    def run_py(self, *argv):
        return subprocess.run(
            [sys.executable, *map(str, argv)],
            env=self.env,
            cwd=self.workspace,
            capture_output=True,
            text=True,
        )

    def glb_artifact(self):
        return self.workspace / ".img2" / "artifacts" / "img2glb" / "photo.glb"

    def write_generate_state(self, stem="photo"):
        state_dir = self.workspace / ".img2"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps({
            "version": 1,
            "workspace": str(self.workspace.resolve()),
            "plugins": {"img2glb": {"lastGenerate": {"stem": stem}}},
        }) + "\n", encoding="utf-8")


class ProbeTests(PluginCase):
    def test_probe_valid_image_emits_plan(self):
        proc = self.run_py(TOOL, "--probe", "--image", self.image, "--workspace", self.workspace)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["kind"], "img2.probe")
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["plugin"], "img2glb")
        self.assertEqual(doc["input"], str(self.image.resolve()))
        self.assertEqual(doc["wouldEmit"], [
            ".img2/artifacts/img2glb/photo.glb",
            ".img2/artifacts/img2glb/photo.report.json",
        ])

    def test_probe_records_state_in_own_subtree(self):
        proc = self.run_py(TOOL, "--probe", "--image", self.image, "--workspace", self.workspace)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads((self.workspace / ".img2" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["plugins"]["img2glb"]["lastProbe"]["stem"], "photo")

    def test_probe_writes_no_artifacts(self):
        self.run_py(TOOL, "--probe", "--image", self.image, "--workspace", self.workspace)
        self.assertFalse((self.workspace / ".img2" / "artifacts").exists())

    def test_probe_missing_image_exits_2(self):
        proc = self.run_py(TOOL, "--probe", "--image", self.workspace / "nope.png",
                           "--workspace", self.workspace)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr)

    def test_probe_empty_image_exits_2(self):
        empty = self.workspace / "empty.png"
        empty.write_bytes(b"")
        proc = self.run_py(TOOL, "--probe", "--image", empty, "--workspace", self.workspace)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("empty", proc.stderr)


class GateTests(PluginCase):
    def test_gate_passes_on_valid_glb(self):
        write_minimal_glb(self.glb_artifact())
        proc = self.run_py(GATE, "--workspace", self.workspace, "--input", "photo.png")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["kind"], "img2.gate-verdict")
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["gate"], "glb-artifact")
        self.assertEqual(doc["plugin"], "img2glb")
        self.assertEqual(doc["status"], "pass")
        self.assertEqual(doc["reasons"], [])
        self.assertEqual(doc["evidence"]["bytes"], 20)
        self.assertEqual(doc["evidence"]["declaredLength"], 20)

    def test_gate_fails_when_artifact_missing(self):
        proc = self.run_py(GATE, "--workspace", self.workspace, "--input", "photo.png")
        self.assertEqual(proc.returncode, 1)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["status"], "fail")
        self.assertTrue(doc["reasons"])

    def test_gate_fails_on_bad_magic(self):
        target = self.glb_artifact()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"NOPE" + struct.pack("<II", 2, 20) + b"\x00" * 8)
        proc = self.run_py(GATE, "--workspace", self.workspace, "--input", "photo.png")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["status"], "fail")

    def test_gate_fails_on_declared_length_not_over_header(self):
        write_minimal_glb(self.glb_artifact(), declared_length=12)
        proc = self.run_py(GATE, "--workspace", self.workspace, "--input", "photo.png")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["status"], "fail")

    def test_gate_resolves_input_from_state(self):
        write_minimal_glb(self.glb_artifact())
        self.write_generate_state()
        proc = self.run_py(GATE, "--workspace", self.workspace)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "pass")


class GateRunnerTests(PluginCase):
    def run_gate_runner(self):
        return self.run_py("-m", "img2_core.gate_runner",
                           "--plugin-dir", PLUGIN_DIR, "--workspace", self.workspace)

    def test_runner_aggregates_pass(self):
        write_minimal_glb(self.glb_artifact())
        self.write_generate_state()
        proc = self.run_gate_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertEqual(doc["kind"], "img2.gate-run")
        self.assertFalse(doc["stopped"])
        (result,) = doc["results"]
        self.assertEqual(result["gate"], "glb-artifact")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["envelope"]["kind"], "img2.gate-verdict")
        self.assertEqual(result["envelope"]["plugin"], "img2glb")

    def test_runner_stops_on_blocking_fail(self):
        proc = self.run_gate_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["stopped"])
        (result,) = doc["results"]
        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["reasons"])


if __name__ == "__main__":
    unittest.main()
