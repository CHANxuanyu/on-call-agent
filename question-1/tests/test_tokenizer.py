from app.indexing.tokenizer import Tokenizer


def test_tokenizer_keeps_common_technical_ascii_terms_intact() -> None:
    tokenizer = Tokenizer()

    terms = [token.term for token in tokenizer.tokenize("read-only redis-cluster error_code api/v1")]

    assert terms == ["read-only", "redis-cluster", "error_code", "api/v1"]


def test_tokenizer_normalizes_full_width_query_forms() -> None:
    tokenizer = Tokenizer()

    terms = [token.term for token in tokenizer.tokenize("ＡＰＩ／v1 ＆")]

    assert terms == ["api/v1", "&"]


def test_tokenizer_ignores_separator_noise_but_keeps_ampersand() -> None:
    tokenizer = Tokenizer()

    terms = [token.term for token in tokenizer.tokenize("--- / _ &")]

    assert terms == ["&"]


def test_tokenizer_keeps_cjk_behavior_simple_and_stable() -> None:
    tokenizer = Tokenizer()

    terms = [token.term for token in tokenizer.tokenize("故障处理")]

    assert terms == ["故障", "障处", "处理"]
