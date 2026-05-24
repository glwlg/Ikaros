from core.file_artifacts import extract_markdown_file_link_rows


def test_extract_markdown_file_link_rows_accepts_angle_bracket_path(tmp_path):
    report = tmp_path / "report with spaces.pdf"
    report.write_bytes(b"%PDF-1.7")

    rows = extract_markdown_file_link_rows(
        f"下载：[报告](<{report}>)",
    )

    assert rows == [
        {
            "kind": "document",
            "path": str(report.resolve()),
            "filename": "report with spaces.pdf",
            "caption": "",
        }
    ]
