import pytest

from app.fetchers.dynamic_fetcher import DynamicFetcher


class FakeNode:
    def __init__(self, attrs):
        self.attrs = attrs

    async def get_attribute(self, name):
        return self.attrs.get(name)


class FakeLocator:
    def __init__(self, count):
        self._count = count
        self.clicked = 0

    async def count(self):
        return self._count

    @property
    def first(self):
        return self

    async def click(self, timeout=1500):
        self.clicked += 1


class FakePage:
    def __init__(self):
        self.url = "https://example.com/listing"
        self.buttons = {
            "photos": FakeLocator(1),
            "gallery": FakeLocator(0),
            "see all": FakeLocator(0),
            "view more": FakeLocator(1),
        }
        self.links = {
            "photos": FakeLocator(0),
            "gallery": FakeLocator(1),
            "see all": FakeLocator(0),
            "view more": FakeLocator(0),
        }
        self.wait_calls = 0

    async def query_selector_all(self, selector):
        if selector == "img":
            return [
                FakeNode({"src": "/a.jpg", "data-src": "/a-large.jpg"}),
                FakeNode({"srcset": "/b-small.jpg 200w, /b-large.jpg 1000w"}),
            ]
        if selector == "video":
            return [
                FakeNode({"src": "/clip.mp4", "poster": "/poster.jpg"}),
            ]
        if selector == "video source, audio source":
            return [
                FakeNode({"src": "/clip-alt.webm"}),
                FakeNode({"src": "/theme.mp3"}),
            ]
        raise AssertionError(selector)

    def get_by_role(self, role, name):
        key = name.lower()
        if role == "button":
            return self.buttons[key]
        return self.links[key]

    async def wait_for_timeout(self, _):
        self.wait_calls += 1


@pytest.mark.asyncio
async def test_collect_images_handles_lazy_and_srcset():
    fetcher = DynamicFetcher()
    page = FakePage()

    images = await fetcher._collect_images(page)

    assert "https://example.com/a.jpg" in images
    assert "https://example.com/a-large.jpg" in images
    assert "https://example.com/b-small.jpg" in images
    assert "https://example.com/b-large.jpg" in images


@pytest.mark.asyncio
async def test_click_gallery_candidates_clicks_matching_controls():
    fetcher = DynamicFetcher()
    page = FakePage()

    await fetcher._click_gallery_candidates(page)

    assert page.buttons["photos"].clicked == 1
    assert page.buttons["view more"].clicked == 1
    assert page.links["gallery"].clicked == 1
    assert page.wait_calls >= 3


@pytest.mark.asyncio
async def test_collect_videos_handles_video_and_source_nodes():
    fetcher = DynamicFetcher()
    page = FakePage()

    videos = await fetcher._collect_videos(page)

    assert "https://example.com/clip.mp4" in videos
    assert "https://example.com/poster.jpg" in videos
    assert "https://example.com/clip-alt.webm" in videos
    assert "https://example.com/theme.mp3" in videos
