import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("pack_dataset", Path(__file__).parents[1] / "scripts" / "pack_dataset.py")
pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack)


class PackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.dataset = self.base / "dataset"
        self.episode = self.dataset / "episode-1000"
        self.episode.mkdir(parents=True)
        (self.episode / "manifest.json").write_text('{"status":"success"}')
        (self.episode / "publication.json").write_text(json.dumps({"validation_passed": True, "manifest_sha256": pack.sha256(self.episode / "manifest.json")}))
        (self.episode / "frames").mkdir()
        (self.episode / "frames" / ("long-name-" + "x" * 120 + ".jpg")).write_bytes(bytes(range(256)) * 30)
        (self.episode / "state.parquet").write_bytes(b"PAR1\x00\xffexact bytes")
        self.output = self.base / "packed"

    def tearDown(self):
        self.temp.cleanup()

    def test_random_access_exact_bytes_and_shard_hashes(self):
        result = pack.pack_dataset(self.dataset, self.output, max_bytes=16000, max_files=2)
        self.assertGreater(len(result["shards"]), 1)
        recovered = set()
        for shard in result["shards"]:
            archive = self.output / shard["archive"]
            self.assertEqual(pack.sha256(archive), shard["sha256"])
            self.assertEqual(pack.sha256(self.output / shard["index"]), shard["index_sha256"])
            index = json.loads((self.output / shard["index"]).read_text())
            for entry in reversed(index["entries"]):
                self.assertEqual(pack.read_indexed(archive, entry), (self.dataset / entry["path"]).read_bytes())
                recovered.add(entry["path"])
        self.assertEqual(recovered, {p.relative_to(self.dataset).as_posix() for p in self.episode.rglob("*") if p.is_file()})
        self.assertTrue((self.episode / "manifest.json").exists())
        with self.assertRaises(FileExistsError):
            pack.pack_dataset(self.dataset, self.output)

    def test_corruption_is_detected(self):
        result = pack.pack_dataset(self.dataset, self.output)
        shard = result["shards"][0]
        entry = json.loads((self.output / shard["index"]).read_text())["entries"][0]
        archive = self.output / shard["archive"]
        with archive.open("r+b") as stream:
            stream.seek(entry["offset"])
            stream.write(b"CORRUPTED")
        with self.assertRaisesRegex(ValueError, "checksum"):
            pack.read_indexed(archive, entry)

    def test_invalid_publication_is_not_published(self):
        (self.episode / "manifest.json").write_text("modified")
        with self.assertRaisesRegex(ValueError, "receipt"):
            pack.pack_dataset(self.dataset, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.base.glob("*.packing.lock")))
        self.assertFalse(list(self.base.glob(".*.packing-*")))

    def test_unpublished_and_symlink_inputs(self):
        (self.episode / "publication.json").unlink()
        with self.assertRaisesRegex(ValueError, "No validated"):
            pack.pack_dataset(self.dataset, self.output)
        (self.episode / "publication.json").write_text(json.dumps({"validation_passed": True, "manifest_sha256": pack.sha256(self.episode / "manifest.json")}))
        (self.episode / "linked").symlink_to(self.episode / "manifest.json")
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            pack.pack_dataset(self.dataset, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
