from core.artifact_ledger import get_artifact_ledger, record_artifact_receipts


def test_artifact_ledger_updates_existing_receipt_by_file_key(tmp_path):
    image_path = (tmp_path / "image.png").resolve()
    image_path.write_bytes(b"png")
    user_data: dict = {}

    first = record_artifact_receipts(
        user_data,
        [
            {
                "path": str(image_path),
                "kind": "photo",
                "filename": "image.png",
                "caption": "",
            }
        ],
        status="pending",
        source="agent_tool",
    )
    second = record_artifact_receipts(
        user_data,
        [
            {
                "path": str(image_path),
                "kind": "photo",
                "filename": "image.png",
                "caption": "",
            }
        ],
        status="delivered",
        source="result_files",
        target="telegram:chat-1",
    )

    ledger = get_artifact_ledger(user_data)
    assert len(first) == 1
    assert len(second) == 1
    assert len(ledger) == 1
    assert ledger[0]["status"] == "delivered"
    assert ledger[0]["target"] == "telegram:chat-1"
