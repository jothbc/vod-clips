"""Feature registry dispatch."""

from __future__ import annotations

import pytest

from reels.features import get_feature, list_feature_info
from reels.features.captions import CaptionsFeature
from reels.features.cleanup import CleanupFeature
from reels.features.publish import PublishFeature
from reels.features.reels import ReelsFeature
from reels.progress import (
    CAPTIONS_PHASE_WEIGHTS,
    CLEANUP_PHASE_WEIGHTS,
    PUBLISH_PHASE_WEIGHTS,
    REELS_PHASE_WEIGHTS,
)


def test_get_feature_returns_known_features():
    assert isinstance(get_feature("reels"), ReelsFeature)
    assert isinstance(get_feature("cleanup"), CleanupFeature)
    assert isinstance(get_feature("captions"), CaptionsFeature)
    assert isinstance(get_feature("publish"), PublishFeature)


def test_get_feature_unknown_raises():
    with pytest.raises(KeyError):
        get_feature("does-not-exist")


def test_feature_phase_weights_sum_to_100():
    assert sum(REELS_PHASE_WEIGHTS.values()) == 100
    assert sum(CLEANUP_PHASE_WEIGHTS.values()) == 100
    assert sum(CAPTIONS_PHASE_WEIGHTS.values()) == 100
    assert sum(PUBLISH_PHASE_WEIGHTS.values()) == 100


def test_list_feature_info_includes_publish():
    info = {f["id"]: f for f in list_feature_info()}
    assert info["reels"]["enabled"] is True
    assert info["cleanup"]["enabled"] is True
    assert info["reels_library"]["enabled"] is True
    assert info["captions"]["enabled"] is True
    assert info["publish"]["enabled"] is True
