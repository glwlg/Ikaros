from platforms.weixin.formatter import markdown_to_weixin_text
from platforms.weixin.mapper import map_weixin_message


def test_markdown_to_weixin_text_downgrades_links_and_emphasis():
    rendered = markdown_to_weixin_text(
        "## 标题\n**加粗** [OpenAI](https://openai.com)\n`code`"
    )
    assert "标题" in rendered
    assert "加粗" in rendered
    assert "OpenAI: https://openai.com" in rendered
    assert "`" not in rendered


def test_map_weixin_message_extracts_text_items_and_placeholders():
    message = map_weixin_message(
        {
            "from_user_id": "wx-user-1",
            "from_user_name": "Alice",
            "client_id": "msg-1",
            "create_time_ms": 1710000000000,
            "item_list": [
                {"type": 1, "text_item": {"text": "hello"}},
                {"type": 2},
                {"type": 4, "file_item": {"file_name": "report.pdf"}},
            ],
            "context_token": "ctx-1",
        }
    )

    assert message.platform == "weixin"
    assert message.user.id == "wx-user-1"
    assert message.chat.id == "wx-user-1"
    assert message.text == "hello\n(image)\n(file: report.pdf)"
