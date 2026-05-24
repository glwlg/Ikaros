from core.task_confirmation import is_confirmation_expired


def test_waiting_user_with_empty_deadline_is_expired():
    assert (
        is_confirmation_expired(
            {
                "status": "waiting_user",
                "needs_confirmation": True,
                "confirmation_deadline": "",
            }
        )
        is True
    )


def test_non_confirmation_task_without_deadline_is_not_expired():
    assert is_confirmation_expired({"status": "running"}) is False
