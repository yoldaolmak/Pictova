"""The supported engine must not depend on legacy processor/validation modules."""

import ast
from pathlib import Path

from PIL import Image

from src.core import media_quality as legacy_quality
from src.core import processor as legacy_processor
from src.pictova.engine import image_processing, media_validation
from src.pictova.engine.processor import process_selected_images


def test_legacy_imports_remain_identical_to_native_implementations():
    assert legacy_processor.YOImageProcessor is image_processing.YOImageProcessor
    assert legacy_processor.get_vil_images is image_processing.get_vil_images
    assert legacy_processor.process_downloads_images is image_processing.process_downloads_images
    assert legacy_quality.validate_metadata is media_validation.validate_metadata
    assert legacy_quality.validate_processed_asset is media_validation.validate_processed_asset
    assert legacy_quality.normalize_text is media_validation.normalize_text
    assert legacy_quality.GENERIC_ANCHORS is media_validation.GENERIC_ANCHORS


def test_native_modules_no_longer_import_legacy_processor_or_validation():
    project = Path(__file__).resolve().parents[2]
    for name in ("processor", "selector", "quality"):
        tree = ast.parse((project / "src/pictova/engine" / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("src.core.processor", "src.core.media_quality")
            if isinstance(node, ast.Import):
                assert all(
                    alias.name not in ("src.core.processor", "src.core.media_quality")
                    for alias in node.names
                )


def test_native_image_processing_still_produces_webp_and_details(tmp_path):
    photo = tmp_path / "sample-photograph.jpg"
    Image.new("RGB", (1600, 1000), (90, 125, 165)).save(photo, quality=90)
    output = process_selected_images([str(photo)], work_dir=str(tmp_path / "processed"))
    files = output["processed_images"]
    assert len(files) == 1
    assert files[0].endswith(".webp")
    with Image.open(files[0]) as image:
        assert image.format == "WEBP"
        assert image.width > 0 and image.height > 0
    assert output["processed_details"][files[0]]["final_size"]
