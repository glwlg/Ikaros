import importlib.util
from pathlib import Path

import pytest


def _load_wechat_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "extension"
        / "skills"
        / "learned"
        / "article_publisher"
        / "scripts"
        / "ap_utils"
        / "wechat.py"
    )
    spec = importlib.util.spec_from_file_location(
        "article_publisher_wechat_test",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_format_wechat_inline_image_html_adds_responsive_spacing():
    module = _load_wechat_module()

    html = module.format_wechat_inline_image_html("https://mmbiz.example/image.png")

    assert 'style="margin:18px 0 20px;text-align:center;"' in html
    assert 'src="https://mmbiz.example/image.png"' in html
    assert "width:100%" in html
    assert "height:auto" in html


def test_summarize_wechat_style_roundtrip_reports_preserved_styles():
    module = _load_wechat_module()

    status = module.summarize_wechat_style_roundtrip(
        original_html='<p style="color:#111">正文</p>',
        draft_data={"news_item": [{"content": '<p style="color:#111">正文</p>'}]},
    )

    assert "样式回读已保留" in status
    assert "style 1/1" in status


def test_summarize_wechat_style_roundtrip_reports_stripped_styles():
    module = _load_wechat_module()

    status = module.summarize_wechat_style_roundtrip(
        original_html='<p style="color:#111">正文</p>',
        draft_data={"news_item": [{"content": "<p>正文</p>"}]},
    )

    assert "未发现 `style`" in status


def test_prepare_wechat_upload_image_keeps_small_png():
    module = _load_wechat_module()

    payload, filename, content_type = module.prepare_wechat_upload_image(
        b"\x89PNG\r\n\x1a\nsmall",
        filename="cover.png",
        max_bytes=1024,
        max_width=900,
    )

    assert payload == b"\x89PNG\r\n\x1a\nsmall"
    assert filename == "cover.png"
    assert content_type == "image/png"


@pytest.mark.asyncio
async def test_publish_to_wechat_uses_styled_images_and_verifies_roundtrip():
    module = _load_wechat_module()

    class FakePublisher:
        def __init__(self):
            self.content_html = ""

        async def upload_cover_image(self, _image_bytes):
            return "thumb-media"

        async def upload_article_image(self, _image_bytes):
            return "https://mmbiz.example/body.png"

        async def add_draft(self, *, content_html, **_kwargs):
            self.content_html = content_html
            return "draft-media"

        async def get_draft(self, _media_id):
            return {"news_item": [{"content": self.content_html}]}

    publisher = FakePublisher()

    status = await module.publish_to_wechat(
        publisher=publisher,
        article_data={
            "title": "测试标题",
            "author": "硅基天平",
            "digest": "摘要",
            "sections": [
                {"content": '<p style="line-height:1.8">正文</p>'},
            ],
        },
        cover_bytes=b"cover",
        section_images={0: b"body"},
        account_name="测试号",
    )

    assert "已发布到公众号草稿箱（测试号）" in status
    assert "样式回读已保留" in status
    assert "width:100%" in publisher.content_html
    assert "margin:18px 0 20px" in publisher.content_html
