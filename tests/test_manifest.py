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

    The manifest version must equal the tag it ships under, and this
    repository ships both stable releases and prereleases, so the suffix is
    optional rather than required.
    """
    version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+(-(?:alpha|beta|rc)\.\d+)?", version), (
        f"{version!r} is not an X.Y.Z or X.Y.Z-beta.N version"
    )
