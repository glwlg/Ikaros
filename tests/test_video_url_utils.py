import pytest

from utils import extract_pure_video_url, extract_video_url, is_video_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.douyin.com/video/7298145681699622182",
        "https://v.douyin.com/iRNBho6u/",
        "https://www.iesdouyin.com/share/video/7298145681699622182/",
        "https://weibo.com/7827771738/N4xlMvjhI",
        "https://m.weibo.cn/status/4189191225395228",
        "https://m.weibo.cn/detail/4189191225395228",
        "https://weibo.com/tv/show/1034:4797699866951785",
        "https://video.weibo.com/show?fid=1034:4967272104787984",
    ],
)
def test_weibo_and_douyin_video_urls_are_supported(url):
    assert is_video_url(url)
    assert extract_video_url(f"下载这个视频 {url}") == url
    assert extract_pure_video_url(url) == url


def test_douyin_share_text_extracts_short_url():
    text = "复制打开抖音，看看【作者的作品】 https://v.douyin.com/iRNBho6u/ 12/31"

    assert extract_video_url(text) == "https://v.douyin.com/iRNBho6u/"


def test_regular_web_url_is_not_misclassified_as_video():
    assert not is_video_url("https://example.com/article")
    assert extract_video_url("https://example.com/article") is None
    assert extract_pure_video_url("https://example.com/article") is None
