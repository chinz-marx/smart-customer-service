"""测试环境的公共安全配置。"""

import pytest


@pytest.fixture(autouse=True)
def disable_real_model_calls(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """普通测试强制使用占位Key，只有live_llm测试允许读取真实.env。

    这样开发机配置真实模型后，运行pytest也不会意外产生网络请求和模型费用。
    """
    if request.node.get_closest_marker("live_llm"):
        return

    monkeypatch.setenv("DOUBAO_API_KEY", "YOUR_TEST_KEY")
    monkeypatch.setenv("UNDERSTANDING_API_KEY", "YOUR_TEST_KEY")
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "false")