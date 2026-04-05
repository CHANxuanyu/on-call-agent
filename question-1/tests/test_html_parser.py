from app.core.html_parser import parse_html_document


def test_parser_ignores_non_visible_tags_and_decodes_entities() -> None:
    parsed = parse_html_document(
        document_id="doc-001",
        html="""
        <html>
            <head>
                <title>Title &amp; Alerts</title>
                <style>.replication { display: block; }</style>
            </head>
            <body>
                <noscript>replication fallback text</noscript>
                <script>var keyword = "replication";</script>
                <p>Ops &amp; Support handled 故障.</p>
                <div hidden>hidden body text</div>
            </body>
        </html>
        """,
    )

    assert parsed.title == "Title & Alerts"
    assert "Ops & Support handled 故障." in parsed.visible_text
    assert "replication" not in parsed.visible_text
    assert "hidden body text" not in parsed.visible_text


def test_parser_falls_back_to_h1_then_document_id() -> None:
    with_h1 = parse_html_document(
        document_id="doc-002",
        html="<html><body><h1>Malformed <b>Title</body></html>",
    )
    with_id_only = parse_html_document(
        document_id="doc-003",
        html="<html><body><p>No heading here</p></body></html>",
    )

    assert with_h1.title == "Malformed Title"
    assert with_id_only.title == "doc-003"


def test_parser_avoids_head_text_and_normalizes_unicode_safely() -> None:
    parsed = parse_html_document(
        document_id="doc-004",
        html="""
        <html>
            <head>
                <title>Head Only</title>
                <meta name="description" content="do not index me">
            </head>
            <p>ＡＰＩ／v1 ＆ read-only 故障</p>
        </html>
        """,
    )

    assert parsed.visible_text == "API/v1 & read-only 故障"
    assert "Head Only" not in parsed.visible_text
