from __future__ import annotations

from dataclasses import dataclass
import unicodedata


SEARCHABLE_SYMBOLS = {"&"}
ASCII_TOKEN_SEPARATORS = {"-", "_", "/"}


@dataclass(frozen=True, slots=True)
class Token:
    term: str
    start: int
    end: int


class Tokenizer:
    """Tokenizes mixed English/Chinese text for lexical matching."""

    def tokenize(self, text: str) -> list[Token]:
        text = unicodedata.normalize("NFKC", text)
        tokens: list[Token] = []
        index = 0

        while index < len(text):
            char = text[index]

            if char.isspace():
                index += 1
                continue

            if _is_ascii_term_char(char):
                start = index
                index = _consume_ascii_token(text, start)
                term = text[start:index].casefold()
                tokens.append(Token(term=term, start=start, end=index))
                continue

            if _is_cjk(char):
                start = index
                index += 1
                while index < len(text) and _is_cjk(text[index]):
                    index += 1
                tokens.extend(_build_cjk_tokens(text[start:index], offset=start))
                continue

            if char in SEARCHABLE_SYMBOLS:
                tokens.append(Token(term=char, start=index, end=index + 1))

            index += 1

        return tokens


def _is_ascii_term_char(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _consume_ascii_token(text: str, start: int) -> int:
    index = start + 1

    while index < len(text):
        char = text[index]
        if _is_ascii_term_char(char):
            index += 1
            continue

        if _is_internal_ascii_separator(text, index):
            index += 1
            continue

        break

    return index


def _is_internal_ascii_separator(text: str, index: int) -> bool:
    if text[index] not in ASCII_TOKEN_SEPARATORS:
        return False
    if index == 0 or index + 1 >= len(text):
        return False
    return _is_ascii_term_char(text[index - 1]) and _is_ascii_term_char(text[index + 1])


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _build_cjk_tokens(text: str, offset: int) -> list[Token]:
    if len(text) == 1:
        return [Token(term=text, start=offset, end=offset + 1)]

    return [
        Token(term=text[index : index + 2], start=offset + index, end=offset + index + 2)
        for index in range(len(text) - 1)
    ]
