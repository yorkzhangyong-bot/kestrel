"""The lexical test embedding (feature 011, research D8): a hashed bag of words, L2-normalised and stable across
processes, so the offline suite can state floors and thresholds on a meaningful distance scale — identical texts at
0, texts sharing no token at 2, one token of six changed at 2 − 2·5/6 (FR-014, SC-008). Placeholder words only."""
import math
import zlib

import pytest

from tests.support import StubEmbeddingFunction

FEATURE = "011"

DIM = 256


def bucket(word: str) -> int:
    return zlib.crc32(word.encode("utf-8")) % DIM


def embed(text: str, function: StubEmbeddingFunction | None = None) -> list[float]:
    """The stub's own (float64) vector; ChromaDB's `__call__` wrapper hands the collection a float32 copy."""
    return (function or StubEmbeddingFunction()).embed(text)


def squared_distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def close(value: float):
    return pytest.approx(value, abs=1e-9)


def test_identical_texts_embed_at_squared_distance_zero():  # FR-014
    assert squared_distance(embed("placeholder approach alpha"), embed("placeholder approach alpha")) == 0.0


def test_two_words_in_different_buckets_embed_at_two():  # FR-014
    assert bucket("orchestra") != bucket("placeholder")
    assert squared_distance(embed("orchestra"), embed("placeholder")) == close(2.0)


def test_every_vector_has_unit_length():  # FR-014
    for text in ("placeholder", "placeholder approach alpha step one variant plain", "<placeholder prompt 1>"):
        assert math.sqrt(sum(v * v for v in embed(text))) == close(1.0)


def test_the_same_text_embeds_identically_across_calls_and_instances():  # FR-014, SC-008
    text = "placeholder approach beta variant two framing"
    one = StubEmbeddingFunction()
    assert embed(text, one) == embed(text, one) == embed(text, StubEmbeddingFunction())


def test_changing_one_token_of_six_lands_at_two_minus_two_times_five_sixths():  # FR-014
    words = ["placeholder", "approach", "alpha", "step", "one", "variant", "plain"]
    assert len({bucket(w) for w in words}) == len(words)   # collision-free, so the distance is exact
    base = "placeholder approach alpha step one variant"
    changed = "placeholder approach alpha step one plain"
    assert squared_distance(embed(base), embed(changed)) == close(2 - 2 * 5 / 6)


def test_tokenisation_is_lower_case_alphanumeric():  # FR-014
    # `direct_injection` yields the two tokens `direct` and `injection`; case and punctuation do not matter.
    assert embed("direct_injection") == embed("Direct, injection!")
    assert squared_distance(embed("direct_injection"), embed("direct injection")) == 0.0
    assert squared_distance(embed("direct"), embed("direct_injection")) == close(2 - 2 * (1 / math.sqrt(2)))


def test_the_chromadb_call_returns_the_same_vectors_at_float32_precision():  # FR-014
    function = StubEmbeddingFunction()
    text = "placeholder approach alpha step one variant plain"
    called = [float(v) for v in function([text])[0]]
    assert len(called) == DIM and called == pytest.approx(embed(text, function), abs=1e-6)


def test_dim_model_name_and_registered_name():  # FR-014
    function = StubEmbeddingFunction()
    assert len(embed("placeholder", function)) == DIM and function.get_config()["dim"] == DIM
    assert StubEmbeddingFunction.MODEL_NAME == "kestrel-lexical-stub"
    assert StubEmbeddingFunction.name() == "kestrel_stub"   # the registered name ChromaDB persists is unchanged


def test_an_empty_text_is_the_zero_vector():  # FR-014
    assert embed("") == [0.0] * DIM


def test_config_round_trips():  # FR-014, SC-008
    function = StubEmbeddingFunction()
    rebuilt = StubEmbeddingFunction.build_from_config(function.get_config())
    assert rebuilt.get_config() == function.get_config() == {"dim": DIM}
    assert embed("placeholder approach", rebuilt) == embed("placeholder approach", function)
