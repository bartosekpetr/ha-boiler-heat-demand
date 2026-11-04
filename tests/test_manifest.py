import json
import pathlib
import re

MANIFEST = pathlib.Path(__file__).parent.parent / "custom_components" / "boiler_heat_demand" / "manifest.json"


def test_manifest_version_is_plain_semver():
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{version!r} is not a stable X.Y.Z version"
