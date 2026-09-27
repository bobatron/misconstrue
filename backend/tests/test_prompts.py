from app.core.prompts import split_prompts


def _texts(masked, n):
    return [p["text"] for p in split_prompts(masked, n)]


def test_phrases_stay_together_and_long_ones_split_evenly():
    masked = "Watson found peace while exploring the island. Government provides available data."
    assert _texts(masked, 3) == [
        "Watson found peace", "while exploring", "the island", "Government provides", "available data",
    ]


def test_even_split():
    # 7 words at 3 per prompt -> 3 + 2 + 2, never a lone word at the end
    assert [len(p["tokens"]) for p in split_prompts("a b c d e f g", 3)] == [3, 2, 2]


def test_lone_words_join_a_neighbour():
    assert _texts("Frank front, test rest, fiber tribe. End, army, use.", 3) == [
        "Frank front", "test rest", "fiber tribe", "End army use",
    ]


def test_one_word_per_prompt():
    assert _texts("Hello there, friend.", 1) == ["Hello", "there", "friend"]


def test_token_indices_cover_everything_in_order():
    masked = "Watson found peace while exploring the island. Government provides available data."
    prompts = split_prompts(masked, 3)
    assert [i for p in prompts for i in p["tokens"]] == list(range(len(masked.split())))
    assert all(1 <= len(p["tokens"]) <= 3 for p in prompts)
