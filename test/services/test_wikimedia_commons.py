"""Offline tests for the first Wikimedia Commons API integration."""
from unittest.mock import Mock, patch

from app.services import wikimedia_commons as commons


def _metadata(name="CC0", url=commons.CC0_URL, restrictions=""):
    fields = {
        "LicenseShortName": name,
        "LicenseUrl": url,
        "Artist": "<b>Historical archive</b>",
        "Restrictions": restrictions,
        "AttributionRequired": "false",
    }
    return {key: {"value": value} for key, value in fields.items()}


def _payload(meta=None):
    return {"query": {"pages": [{
        "pageid": 1234,
        "title": "File:Historical photo.jpg",
        "imageinfo": [{
            "mime": "image/jpeg",
            "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/test.jpg",
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/test.jpg/1600px-test.jpg",
            "width": 2400,
            "height": 1600,
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Historical_photo.jpg",
            "extmetadata": meta or _metadata(),
        }],
    }]}}


@patch.object(commons.requests, "get")
def test_commons_cc0_metadata_is_eligible_for_trial(mock_get):
    mock_get.return_value = Mock(status_code=200, json=lambda: _payload())
    records = commons.search_images("historical ship")
    assert len(records) == 1
    assert records[0]["artist"] == "Historical archive"
    assert records[0]["decision"] == "AUTO_APPROVED"
    assert records[0]["license"] == "CC0"
    assert records[0]["source_page"].startswith("https://commons.wikimedia.org/")
    args, kwargs = mock_get.call_args
    assert kwargs["params"]["iiprop"] == "url|size|mime|extmetadata"
    assert kwargs["params"]["gsrnamespace"] == 6


@patch.object(commons.requests, "get")
def test_commons_cc_by_requires_review(mock_get):
    mock_get.return_value = Mock(json=lambda: _payload(
        _metadata("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")
    ))
    assert commons.search_images("ship")[0]["decision"] == "NEEDS_REVIEW"


@patch.object(commons.requests, "get")
def test_commons_restrictions_require_review(mock_get):
    mock_get.return_value = Mock(json=lambda: _payload(
        _metadata(restrictions="Trademark restrictions")
    ))
    assert commons.search_images("ship")[0]["decision"] == "NEEDS_REVIEW"


@patch.object(commons.requests, "get")
def test_commons_noncommercial_is_rejected(mock_get):
    mock_get.return_value = Mock(json=lambda: _payload(
        _metadata("CC BY-NC", "https://creativecommons.org/licenses/by-nc/4.0/")
    ))
    assert commons.search_images("ship")[0]["decision"] == "REJECTED"


def test_commons_unknown_license_does_not_pass():
    assert commons._classify({"LicenseShortName": ""})[0] == "NEEDS_REVIEW"


def test_commons_blocks_untrusted_download_url():
    assert commons.download_approved_image({
        "decision": "AUTO_APPROVED", "image_url": "https://example.org/image.jpg",
    }) is None


def test_commons_audit_persists(tmp_path):
    path = commons.save_audit(str(tmp_path), [{"decision": "NEEDS_REVIEW"}])
    assert '"NEEDS_REVIEW"' in (tmp_path / "wikimedia-audit.json").read_text()
    assert path.endswith("wikimedia-audit.json")


def test_commons_cc0_with_required_attribution_needs_review():
    decision, reason = commons._classify({
        "LicenseShortName": "CC0",
        "LicenseUrl": commons.CC0_URL,
        "AttributionRequired": "true",
    })
    assert decision == "NEEDS_REVIEW"
    assert "attribution" in reason.lower()


def test_commons_cc0_with_conflicting_copyright_needs_review():
    decision, reason = commons._classify({
        "LicenseShortName": "CC0",
        "LicenseUrl": commons.CC0_URL,
        "Copyrighted": "true",
    })
    assert decision == "NEEDS_REVIEW"
    assert "copyright" in reason.lower()


def test_new_material_sources_pass_preflight():
    from app.services import task
    assert {"wikimedia", "auto"}.issubset(task._SUPPORTED_VIDEO_SOURCES)
