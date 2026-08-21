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
