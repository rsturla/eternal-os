import importlib.metadata as metadata
import os
from pathlib import Path
import sys

assert sys.version_info[:2] == tuple(map(int, sys.argv[1].split(".")))
assert metadata.version(sys.argv[2]) == sys.argv[3]
fixtures = Path(os.environ["TEST_FILES"])
from packaging.version import InvalidVersion, Version
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.requirements import InvalidRequirement, Requirement
from packaging.markers import Marker
from packaging.tags import Tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

assert (
    Version("1.0.dev1")
    < Version("1.0a1")
    < Version("1.0rc1")
    < Version("1.0")
    < Version("1.0.post1")
)
assert Version("2!1.0") > Version("9.0")
assert Version("1.0+linux.1") == Version("1.0+LINUX.1")
constraint = SpecifierSet(">=1.2,!=1.3.*,<2")
assert "1.2.5" in constraint and "1.3.4" not in constraint and "2.0" not in constraint
requirement = Requirement('demo[fast]>=1.0; python_version >= "3.11"')
assert requirement.name == "demo" and requirement.extras == {"fast"}
assert requirement.marker.evaluate({"python_version": "3.14"})
assert not requirement.marker.evaluate({"python_version": "3.10"})
assert Marker('os_name == "posix"').evaluate({"os_name": "posix"})
assert canonicalize_name("Eternal_Fixture.Name") == "eternal-fixture-name"
name, version, build, tags = parse_wheel_filename(
    "eternal_fixture-1.0-py3-none-any.whl"
)
assert name == "eternal-fixture" and version == Version("1.0") and not build
assert Tag("py3", "none", "any") in tags
import platform

system_tags = list(sys_tags())
assert any(
    tag.interpreter == f"cp{sys.version_info.major}{sys.version_info.minor}"
    for tag in system_tags
)
assert Tag("py3", "none", "any") in system_tags
assert any(
    tag.platform.endswith("_" + platform.machine().lower()) for tag in system_tags
)
for function, value, exception in [
    (Version, "not version", InvalidVersion),
    (SpecifierSet, ">=broken", InvalidSpecifier),
    (Requirement, "@@@", InvalidRequirement),
]:
    try:
        function(value)
    except exception:
        pass
    else:
        raise AssertionError((function, value))
