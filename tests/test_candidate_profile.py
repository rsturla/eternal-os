import copy
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import yaml

spec = importlib.util.spec_from_file_location(
    "candidate_profile", Path(__file__).resolve().parents[1] / "scripts/prepare-test-profile.py"
)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)
RPMX = os.environ.get("RPMX", "rpmx")


class ProfilePolicy(unittest.TestCase):
    def test_policy_is_preserved_and_local_paths_keep_their_original_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "profiles/base.yaml"
            base = {
                "document": "rpmx-profile", "version": 1, "name": "production",
                "archs": ["x86_64", "aarch64"], "releasever": "rolling", "dist-tag": ".eternal",
                "packages": {"install": ["eternal-base", "compiler-policy"]},
                "options": {"weak_deps": False, "docs": False},
                "builder": {"image": "example.invalid/builder:44"},
                "paths": {"prefix": "/usr", "libdir": "/usr/lib64"},
                "repositories": [
                    {"id": "production", "baseurl": "https://example.invalid/$releasever/$basearch",
                     "gpgkey": "file://keys/release.asc", "repo-gpgcheck": True, "priority": 30,
                     "auth": {"username": "env:REPO_USER", "password": "/private/password"}},
                    {"id": "bootstrap", "baseurl": "file://../bootstrap/$basearch",
                     "exclude": ["already-excluded"]},
                    {"id": "updates", "metalink": "https://example.invalid/metalink?arch=$basearch",
                     "gpgkey": None},
                    {"id": "signed-local", "baseurl": "file:///private/repository",
                     "gpgkey": "/private/keys/release.asc"},
                ],
            }
            original = copy.deepcopy(base)
            generated = candidate.relocate_profile(base, source, "aarch64", {"candidate-lib"}, root / "repository")
            self.assertEqual(base, original, "the base policy object must not be changed")
            self.assertEqual(generated["archs"], ["aarch64"])
            for key in base.keys() - {"archs", "repositories"}:
                self.assertEqual(generated[key], base[key], key)
            production, bootstrap, updates, signed_local = generated["repositories"][1:]
            self.assertEqual(production["gpgkey"], "file://" + str(root / "profiles/keys/release.asc"))
            self.assertEqual(production["auth"], base["repositories"][0]["auth"])
            self.assertTrue(production["repo-gpgcheck"])
            self.assertEqual(production["baseurl"], base["repositories"][0]["baseurl"])
            self.assertEqual(bootstrap["baseurl"], "file://" + str(root / "bootstrap/$basearch"))
            self.assertEqual(bootstrap["exclude"], ["already-excluded", "candidate-lib"])
            self.assertEqual(updates["metalink"], base["repositories"][2]["metalink"])
            self.assertEqual(signed_local["gpgkey"], "/private/keys/release.asc")
            self.assertEqual(signed_local["baseurl"], "file:///private/repository")
            self.assertTrue(all("candidate-lib" in repo["exclude"] for repo in generated["repositories"][1:]))

    def test_wrong_target_and_existing_overlay_are_rejected(self):
        base = {"archs": ["x86_64"], "repositories": [{"id": "published", "baseurl": "https://example.invalid"}]}
        with self.assertRaisesRegex(ValueError, "does not support"):
            candidate.relocate_profile(base, Path("base.yaml"), "aarch64", {"demo"}, Path("repo"))
        base["repositories"][0]["id"] = candidate.CANDIDATE_REPOSITORY
        with self.assertRaisesRegex(ValueError, "already contains"):
            candidate.relocate_profile(base, Path("base.yaml"), "x86_64", {"demo"}, Path("repo"))


@unittest.skipUnless(shutil.which("rpm") and shutil.which(RPMX), "requires host rpm and rpmx")
class CandidateRPMs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.fixtures = Path(cls.temporary.name)

        def build(label, name, version, arch, summary="Candidate fixture"):
            directory = cls.fixtures / label
            directory.mkdir()
            (directory / "stage").mkdir()
            recipe = directory / "package.yaml"
            recipe.write_text(yaml.safe_dump({
                "schema": 2,
                "package": {"name": name, "version": version, "release": 1,
                            "summary": summary, "license": "MIT", "source-date-epoch": 1704067200},
                "outputs": [{"name": name, "arch": arch, "metapackage": True}],
            }))
            target = "x86_64" if arch == "noarch" else arch
            result = subprocess.run([RPMX, "build", str(recipe), "--stage", str(directory / "stage"),
                            "--output", str(directory / "out"), "--arch", target, "--no-tests"],
                           check=False, capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(f"cannot build {label} fixture:\n{result.stdout}\n{result.stderr}")
            return next((directory / "out" / target).glob("*.rpm")), recipe

        cls.native, cls.recipe = build("native", "candidate-lib", "1", "x86_64")
        cls.newer, _ = build("newer", "candidate-lib", "2", "x86_64")
        cls.modified, _ = build("modified", "candidate-lib", "1", "x86_64", "Different immutable payload")
        cls.foreign, _ = build("foreign", "candidate-lib", "1", "aarch64")
        cls.noarch, _ = build("noarch", "candidate-data", "1", "noarch")
        subprocess.run([RPMX, "srpm", str(cls.recipe), "--output", str(cls.fixtures / "srpm"),
                        "--arch", "x86_64", "--unsafe-host-root"], check=True, capture_output=True, text=True)
        cls.srpm = next((cls.fixtures / "srpm").glob("*.src.rpm"))

    def setUp(self):
        self.temporary_case = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_case.cleanup)
        self.root = Path(self.temporary_case.name)
        self.inputs = self.root / "rpms"
        self.inputs.mkdir()
        self.base = self.root / "base.yaml"
        self.base.write_text(yaml.safe_dump({
            "document": "rpmx-profile", "version": 1, "name": "production",
            "archs": ["x86_64", "aarch64"], "releasever": "44",
            "packages": {"install": ["candidate-lib"]},
            "options": {"docs": False, "weak_deps": False},
            "repositories": [{"id": "published", "baseurl": "https://example.invalid/$basearch"}],
        }))
        self.output = self.root / "generated/profile.yaml"

    def add(self, source, name=None):
        target = self.inputs / (name or source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def prepare(self):
        candidate.prepare(self.base, self.inputs, "x86_64", self.output, RPMX)
        profile = yaml.safe_load(self.output.read_text())
        repository = Path(profile["repositories"][0]["baseurl"][7:])
        return profile, repository

    def test_real_binary_and_noarch_rpms_are_indexed_without_changing_inputs(self):
        native = self.add(self.native, "x86_64/native.rpm")
        self.add(self.noarch, "noarch/common.rpm")
        duplicate = self.inputs / "duplicate.rpm"
        duplicate.symlink_to(native)
        before = {path: path.read_bytes() for path in self.inputs.rglob("*.rpm")}
        base_bytes = self.base.read_bytes()
        profile, repository = self.prepare()
        self.assertEqual(self.base.read_bytes(), base_bytes)
        self.assertTrue(duplicate.is_symlink())
        self.assertEqual(before, {path: path.read_bytes() for path in self.inputs.rglob("*.rpm")})
        self.assertEqual(profile["repositories"][1]["exclude"], ["candidate-data", "candidate-lib"])
        manifest = json.loads((repository / "candidate-inputs.json").read_text())
        self.assertEqual(len(manifest["inputs"]["rpms"]), 2)
        self.assertTrue(all(not path.is_symlink() for path in repository.rglob("*")))
        ns = {"repo": "http://linux.duke.edu/metadata/repo", "common": "http://linux.duke.edu/metadata/common"}
        repomd = ET.parse(repository / "repodata/repomd.xml")
        location = repomd.find("repo:data[@type='primary']/repo:location", ns).attrib["href"]
        primary = ET.fromstring(gzip.decompress((repository / location).read_bytes()))
        self.assertEqual({node.text for node in primary.findall("common:package/common:name", ns)},
                         {"candidate-data", "candidate-lib"})
        for package in primary.findall("common:package", ns):
            payload = repository / package.find("common:location", ns).attrib["href"]
            checksum = package.find("common:checksum", ns)
            self.assertEqual(checksum.attrib["type"], "sha256")
            self.assertEqual(candidate.file_digest(payload), checksum.text,
                             "repository RPMs must survive removal of the staging directory")
        # A valid snapshot is reused without replacing metadata or its URL.
        repomd_path = repository / "repodata/repomd.xml"
        old_metadata = repomd_path.read_bytes(), repomd_path.stat().st_mtime_ns
        _, reused = self.prepare()
        self.assertEqual(repository, reused)
        self.assertEqual(old_metadata, (repomd_path.read_bytes(), repomd_path.stat().st_mtime_ns))

    def test_wrong_architecture_is_rejected_before_profile_publication(self):
        self.add(self.foreign)
        with self.assertRaisesRegex(ValueError, "architecture aarch64, expected x86_64 or noarch"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_source_rpm_header_is_rejected_even_with_an_innocent_filename(self):
        self.add(self.srpm, "binary.rpm")
        with self.assertRaisesRegex(ValueError, "source RPM"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_conflicting_versions_and_immutable_payloads_are_rejected(self):
        for other in (self.newer, self.modified):
            with self.subTest(other=other):
                self.add(self.native, "one.rpm")
                self.add(other, "two.rpm")
                with self.assertRaisesRegex(ValueError, "conflicting candidate"):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_corrupt_rpm_reports_the_actual_input_path(self):
        corrupt = self.inputs / "broken.rpm"
        corrupt.write_text("not an RPM")
        with self.assertRaisesRegex(ValueError, "broken.rpm"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_changed_candidate_bytes_get_a_new_repository_identity(self):
        path = self.add(self.native, "candidate.rpm")
        _, old = self.prepare()
        shutil.copy2(self.newer, path)
        _, new = self.prepare()
        self.assertNotEqual(old, new)
        self.assertTrue((old / "repodata/repomd.xml").exists())

    def test_damaged_repository_cannot_be_reused(self):
        self.add(self.native)
        _, repository = self.prepare()
        (repository / "repodata/repomd.xml").write_text("damaged")
        with self.assertRaisesRegex(ValueError, "repository is damaged"):
            self.prepare()

    def test_failed_index_does_not_publish_an_incomplete_profile(self):
        self.add(self.native)
        self.output.parent.mkdir()
        self.output.write_text("previous valid profile")
        original_run = subprocess.run
        with patch.object(candidate.subprocess, "run", wraps=subprocess.run) as run:
            def fail_repo(command, **options):
                if command[0] == RPMX:
                    raise subprocess.CalledProcessError(7, command)
                return original_run(command, **options)
            run.side_effect = fail_repo
            with self.assertRaises(subprocess.CalledProcessError):
                self.prepare()
        self.assertEqual(self.output.read_text(), "previous valid profile")

    def test_output_cannot_replace_the_base_or_enter_the_input_tree(self):
        self.add(self.native)
        for output in (self.base, self.inputs / "profile.yaml"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                candidate.prepare(self.base, self.inputs, "x86_64", output, RPMX)

    def test_empty_candidate_directory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no candidate RPMs"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_cli_publishes_a_profile_and_reports_invalid_inputs(self):
        self.add(self.native)
        command = [os.sys.executable, str(Path(candidate.__file__)),
                   "--profile", str(self.base), "--rpms", str(self.inputs),
                   "--arch", "x86_64", "--output", str(self.output)]
        environment = dict(os.environ, RPMX=RPMX)
        success = subprocess.run(command, env=environment, capture_output=True, text=True, check=True)
        self.assertEqual(success.stdout, "")
        profile = yaml.safe_load(self.output.read_text())
        self.assertEqual(profile["repositories"][0]["id"], candidate.CANDIDATE_REPOSITORY)
        before = self.output.read_bytes()
        self.add(self.foreign, "wrong-architecture.rpm")
        failure = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(failure.returncode, 1)
        self.assertIn("cannot prepare candidate test profile:", failure.stderr)
        self.assertIn("wrong-architecture.rpm", failure.stderr)
        self.assertNotIn("Traceback", failure.stderr)
        self.assertEqual(self.output.read_bytes(), before)
