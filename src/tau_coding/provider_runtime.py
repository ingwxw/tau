import os
from dataclasses import dataclass

from tau_agent.provider import ModelProvider
from tau_ai.deepseek import DeepSeekProvider
from tau_ai.fake import FakeProvider


@dataclass(frozen=True)
class ProviderRuntime:
    provider: ModelProvider
    model: str


def create_provider_runtime(
    provider_name: str,
    model: str | None = None,
) -> ProviderRuntime:
    if provider_name == "fake":
        return ProviderRuntime(
            provider=FakeProvider(),
            model=model or "fake",
        )

    if provider_name == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("缺少环境变量 DEEPSEEK_API_KEY")

        return ProviderRuntime(
            provider=DeepSeekProvider(api_key=api_key),
            model=model or "deepseek-chat",
        )
    raise ValueError(f"不支持的 Provider：{provider_name}")
