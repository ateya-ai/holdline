# Generating document exports

The design source is `docs/holdline.md`. The PDF and Word files are generated from that source, and `docs/exports.json` records their hashes. The test suite fails if one changes without refreshing the export record.

Use Python with `requirements-docs.txt` installed and a headless LibreOffice installation for conversion:

```bash
python scripts/export_docs.py
soffice --headless --convert-to pdf --outdir docs docs/holdline.docx
```

The exporter supports the headings, paragraphs, lists, inline code, and simple tables used by the design note. It is intentionally not a general Markdown converter. Review both content and every rendered page after a source or layout change. Check table breaks, repeated headers, wrapping, clipped text, missing characters, and headings separated from their paragraphs.

When using Codex's document tooling, use its bundled runtime and canonical DOCX renderer for the conversion and page images. In either workflow, keep render intermediates outside the repository.

After checking the final files, run:

```bash
python scripts/record_doc_exports.py
python -m pytest tests/test_documents.py -ra
```

Do not refresh the hashes merely to suppress a test failure; confirm the exports contain the current source first.
