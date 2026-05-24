from types import SimpleNamespace

from core.runtime_quality_report import build_task_quality_report


def test_task_quality_report_counts_failures_and_artifact_receipts():
    report = build_task_quality_report(
        [
            SimpleNamespace(
                status="failed",
                source="user_chat",
                events=[
                    {
                        "event": "artifact_delivery",
                        "extra": {
                            "delivered": [{"filename": "ok.png"}],
                            "failed": [{"filename": "lost.mp4"}],
                        },
                    }
                ],
            ),
            SimpleNamespace(status="waiting_user", source="user_chat", events=[]),
        ]
    )

    assert report["total"] == 2
    assert report["status_counts"]["failed"] == 1
    assert report["status_counts"]["waiting_user"] == 1
    assert report["artifact_delivered"] == 1
    assert report["artifact_failed"] == 1
    assert any("回归测试" in item for item in report["recommendations"])
    assert any("附件投递" in item for item in report["recommendations"])
