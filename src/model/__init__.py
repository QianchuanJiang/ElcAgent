"""模型层：ModelRouter 与 provider 适配（业务代码禁止直连模型 API）。"""

from .router import ModelRouter, ProfileBinding, StubProvider, StubResponse

__all__ = ["ModelRouter", "ProfileBinding", "StubProvider", "StubResponse"]
