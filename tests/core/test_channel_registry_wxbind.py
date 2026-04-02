from __future__ import annotations

from extension.channels.registry import ChannelRegistry


class _FakeAdapter:
    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name
        self.commands: dict[str, object] = {}
        self.message_handler = None
        self.callback_handlers: list[tuple[str, object]] = []

    def register_message_handler(self, handler) -> None:
        self.message_handler = handler

    def on_callback_query(self, pattern: str, handler) -> None:
        self.callback_handlers.append((pattern, handler))

    def on_command(self, command: str, handler, **kwargs) -> None:
        _ = kwargs
        self.commands[str(command)] = handler


class _FakeRuntime:
    def __init__(self) -> None:
        self.adapters: dict[str, _FakeAdapter] = {}

    def register_adapter(self, adapter):
        self.adapters[str(adapter.platform_name)] = adapter
        return adapter

    def get_adapter(self, platform_name: str):
        return self.adapters[str(platform_name)]

    def has_adapter(self, platform_name: str) -> bool:
        return str(platform_name) in self.adapters

    def register_command(self, command: str, handler_func, *, platforms=None, **kwargs) -> None:
        for platform_name in list(platforms or []):
            self.get_adapter(str(platform_name)).on_command(
                command,
                handler_func,
                **kwargs,
            )


def test_channel_registry_registers_wxbind_for_web(monkeypatch):
    registry = ChannelRegistry()
    monkeypatch.setattr(
        registry,
        "_iter_extension_modules",
        lambda: [
            "extension.channels.weixin.channel",
            "extension.channels.web.channel",
        ],
    )

    from extension.channels.web import channel as web_channel
    from extension.channels.weixin import channel as weixin_channel

    monkeypatch.setattr(
        web_channel.WebChannelExtension,
        "enabled",
        lambda self, runtime: True,
    )
    monkeypatch.setattr(
        weixin_channel.WeixinChannelExtension,
        "enabled",
        lambda self, runtime: True,
    )
    monkeypatch.setattr(
        web_channel,
        "WebAdapter",
        lambda: _FakeAdapter("web"),
    )
    monkeypatch.setattr(
        weixin_channel,
        "WeixinAdapter",
        lambda **kwargs: _FakeAdapter("weixin"),
    )

    extensions = registry.scan_extensions()

    assert [extension.platform_name for extension in extensions] == ["web", "weixin"]

    runtime = _FakeRuntime()
    registry.register_extensions(runtime)

    assert "wxbind" in runtime.adapters["web"].commands
    assert "wxbind" in runtime.adapters["weixin"].commands
