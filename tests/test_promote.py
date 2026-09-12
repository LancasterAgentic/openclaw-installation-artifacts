import copy
import contextlib
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
spec = importlib.util.spec_from_file_location("promote", Path(__file__).resolve().parents[1] / "scripts/promote.py")
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((promote.ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_frozen_four_archives_and_destination(self):
        self.assertEqual(len(promote.manifest_rows(self.manifest)), 4)
        changed = copy.deepcopy(self.manifest)
        changed["archives"][0]["url"] = "https://github.com/another/repo/release"
        with self.assertRaises(ValueError):
            promote.manifest_rows(changed)

    def test_links_cannot_expand_publication_scope(self):
        rows = promote.manifest_rows(self.manifest)
        links = {row["file"]: "https://release-assets.githubusercontent.com/github-production-release-asset/1/2?sp=r&sig=fixture" for row in rows}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(promote.signed_links(json.dumps(links), rows), links)
        self.assertEqual(output.getvalue().count("::add-mask::"), 4)
        links["private-source.tar.gz"] = links[rows[0]["file"]]
        with self.assertRaises(ValueError):
            promote.signed_links(json.dumps(links), rows)

    def test_mismatch_prevents_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.tar.gz"
            path.write_bytes(b"fixture")
            row = {"file": path.name, "bytes": 7, "sha256": hashlib.sha256(b"fixture").hexdigest()}
            promote.verify(path, row)
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                promote.verify(path, row)
            path.write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "byte count"):
                promote.verify(path, row)

    def test_private_destination_refused_before_any_download(self):
        with mock.patch.dict(promote.os.environ, {"GITHUB_REPOSITORY": promote.REPOSITORY}), \
             mock.patch.object(promote, "gh", return_value=json.dumps({"full_name": promote.REPOSITORY, "private": True, "visibility": "private"}).encode()), \
             mock.patch.object(promote.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "public artifact"):
                promote.main()
            run.assert_not_called()

    def test_bad_download_prevents_release_creation(self):
        rows = promote.manifest_rows(self.manifest)
        def command(argv, **kwargs):
            if argv[0] == "gh":
                return mock.Mock(returncode=1, stderr=b"HTTP 404")
            Path(argv[argv.index("--output") + 1]).write_bytes(b"wrong archive")
            return mock.Mock(returncode=0)
        with mock.patch.dict(promote.os.environ, {"GITHUB_REPOSITORY": promote.REPOSITORY}), \
             mock.patch.object(promote, "gh", return_value=json.dumps({"full_name": promote.REPOSITORY, "private": False, "visibility": "public"}).encode()) as gh, \
             mock.patch.object(promote, "signed_links", return_value={row["file"]: "https://fixture.test" for row in rows}), \
             mock.patch.object(promote.subprocess, "run", side_effect=command):
            with self.assertRaisesRegex(ValueError, "byte count"):
                promote.main()
            self.assertEqual(gh.call_count, 1)


if __name__ == "__main__":
    unittest.main()
