"""The preview cache changes no proposal byte and only removes repeated previews."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import kernel_engine_v2
from kernel_engine_v2 import FLAT, PreviewCache
from test_kernel_buffered_mill_v2 import MillPeer, engine_for


def declaration(count, bound, picks):
    """Pose every substep of one whole-library mill and return its extensions and preview count."""
    peer = MillPeer(count)
    engine = engine_for(peer)
    original = PreviewCache.__init__.__defaults__
    PreviewCache.__init__.__defaults__ = (bound,)
    try:
        extensions = [engine.pose("first")["seat_decision"]["extensions"][FLAT]]
        for pick in picks:
            engine.buffer.choose(pick)
            extensions.append(engine.pose("next")["seat_decision"]["extensions"][FLAT])
            assert engine.previews.bytes <= max(bound, max(size for _, size in engine.previews.entries.values()))
    finally:
        PreviewCache.__init__.__defaults__ = original
    assert engine.current == engine.root == peer.root
    return extensions, len(peer.preview_prefixes)


@pytest.mark.parametrize("count, picks", [(12, [11, 0, 5, 3, 0, 2]), (30, [0] * 10 + [7, 18, 1])])
def test_cached_previews_keep_every_proposal_byte(count, picks):
    # A zero bound keeps at most one stored preview, so nearly every step asks the bridge again.
    uncached, asked = declaration(count, 0, picks)
    cached, fewer = declaration(count, kernel_engine_v2.PREVIEW_CACHE_BYTES, picks)
    tight, some = declaration(count, 20000, picks)
    assert cached == uncached == tight
    assert fewer < some <= asked
    # Later substeps replay the shared prefix from the cache (about a third of a whole declaration).
    assert fewer * 5 < asked * 4


def test_preview_cache_drops_oldest_entries_past_its_bound():
    cache = PreviewCache(bound=10)
    for key in range(5):
        cache.put((key,), [key, None], 4)
        cache.get((0,))
    assert list(cache.entries) == [(4,), (0,)] and cache.bytes == 8
    assert cache.get((1,)) is None
    huge = cache.put((9,), ["big", None], 50)
    assert list(cache.entries) == [(9,)] and cache.get((9,)) is huge
