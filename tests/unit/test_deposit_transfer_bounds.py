"""DepositPhotos downloads must be finite and filesystem-safe."""

from unittest.mock import MagicMock, patch

import pytest

from src.pictova.providers import deposit


@pytest.mark.parametrize("asset_id", [
    "../123", "../../secret", "123/other", "abc", "", "１２３", "1" * 30,
])
def test_untrusted_asset_id_cannot_escape_cache_directory(tmp_path, asset_id):
    cache = tmp_path / "cache"
    with patch.object(deposit, "_post") as paid_request:
        with pytest.raises(ValueError, match="decimal identifier"):
            deposit.download(asset_id, "offline", dest_dir=str(cache))
    assert not cache.exists()
    paid_request.assert_not_called()


def test_stream_rejects_oversized_transfer_before_writing_excess_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(deposit, "_MAX_LICENSED_IMAGE_BYTES", 8)
    response = MagicMock()
    response.__enter__.return_value.read.side_effect = [b"first", b"second", b""]
    partial = tmp_path / "licensed.jpg.part"
    with patch.object(deposit, "_urlopen_with_retry", return_value=response) as request:
        with pytest.raises(ValueError, match="maximum download size"):
            deposit._stream_download("https://download.example.test/image", partial)
    assert partial.read_bytes() == b"first"
    request.assert_called_once()


def test_stream_rejects_oversized_resumable_file_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(deposit, "_MAX_LICENSED_IMAGE_BYTES", 8)
    partial = tmp_path / "licensed.jpg.part"
    partial.write_bytes(b"ninebytes")
    with patch.object(deposit, "_urlopen_with_retry") as request:
        with pytest.raises(ValueError, match="Saved DepositPhotos transfer"):
            deposit._stream_download("https://download.example.test/image", partial)
    request.assert_not_called()
    assert partial.read_bytes() == b"ninebytes"


def test_existing_oversized_cached_image_is_never_used(tmp_path, monkeypatch):
    monkeypatch.setattr(deposit, "_MAX_LICENSED_IMAGE_BYTES", 8)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "deposit_123.jpg").write_bytes(b"ninebytes")
    with patch.object(deposit, "_post") as paid_request:
        with pytest.raises(ValueError, match="Cached DepositPhotos image"):
            deposit.download("123", "offline", dest_dir=str(cache))
    paid_request.assert_not_called()


def test_resumable_transfer_at_exact_size_limit_still_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(deposit, "_MAX_LICENSED_IMAGE_BYTES", 8)
    partial = tmp_path / "licensed.jpg.part"
    partial.write_bytes(b"first")
    response = MagicMock()
    response.__enter__.return_value.status = 206
    response.__enter__.return_value.read.side_effect = [b"xyz", b""]
    with patch.object(deposit, "_urlopen_with_retry", return_value=response) as request:
        deposit._stream_download("https://download.example.test/image", partial)
    assert partial.read_bytes() == b"firstxyz"
    assert request.call_args.args[0].get_header("Range") == "bytes=5-"
