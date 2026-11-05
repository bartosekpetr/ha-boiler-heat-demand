import json
import pathlib
import re

MANIFEST = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "boiler_heat_demand"
    / "manifest.json"
)


def test_manifest_version_is_semver():
    """X.Y.Z, optionally with a -beta.N / -alpha.N / -rc.N prerelease suffix.

    This repository releases prereleases, so the manifest version has to be
    able to carry the same suffix as the tag it ships under.
    """
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-(?:alpha|beta|rc)\.\d+)?", version), (
        f"{version!r} is not an X.Y.Z or X.Y.Z-beta.N version"
    )
