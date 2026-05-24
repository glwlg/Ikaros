from core.file_artifacts import (
    extract_file_rows_from_text,
    extract_markdown_file_link_rows,
)


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


def test_extract_file_rows_from_text_accepts_relative_labeled_path_with_base_dir(tmp_path):
    video = tmp_path / "video_abc.mp4"
    video.write_bytes(b"mp4")

    rows = extract_file_rows_from_text("文件路径：video_abc.mp4", base_dir=tmp_path)

    assert rows == [
        {
            "kind": "video",
            "path": str(video.resolve()),
            "filename": "video_abc.mp4",
            "caption": "",
        }
    ]
