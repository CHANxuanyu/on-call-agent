from app.indexing.chunker import HtmlSectionChunker


def test_chunker_groups_content_by_h2_and_h3_sections() -> None:
    chunker = HtmlSectionChunker()
    chunks = chunker.chunk_document(
        "doc-001",
        """
        <html>
            <body>
                <h2>Overview</h2>
                <p>Alpha context.</p>
                <p>Beta details.</p>
                <h3>Deep Dive</h3>
                <p>Gamma analysis.</p>
                <ul><li>Delta checklist.</li></ul>
                <h2>Recovery</h2>
                <p>Epsilon action.</p>
            </body>
        </html>
        """,
        title="Chunk Test",
    )

    assert [chunk.section_path for chunk in chunks] == [
        "Overview",
        "Overview > Deep Dive",
        "Recovery",
    ]
    assert chunks[0].text == "Alpha context. Beta details."
    assert chunks[1].text == "Gamma analysis. Delta checklist."
    assert chunks[2].text == "Epsilon action."
