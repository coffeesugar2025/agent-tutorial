"""密钥环与无感轮换：多版本密钥 + kid，签名携带 kid，验签自动选版本。

不修改 ``config.py`` / ``rbac.py``；可通过 :class:`EnvSecretsProvider` 从环境变量
加载密钥环。HMAC-SHA256 实现，token 形如 ``kid.body.signature``。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Mapping, Protocol, runtime_checkable


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@runtime_checkable
class SecretsProvider(Protocol):
    """密钥来源协议：加载 ``kid -> secret`` 映射及当前 active kid。"""

    def load(self) -> dict[str, str]: ...

    def active_kid(self) -> str | None: ...


class EnvSecretsProvider:
    """从环境变量加载密钥：``<PREFIX><KID>`` 为密钥，``<PREFIX>ACTIVE_KID`` 指定版本。"""

    def __init__(self, prefix: str = "ECOM_SECRET_",
                 env: Mapping[str, str] | None = None) -> None:
        self.prefix = prefix
        self.env: Mapping[str, str] = env if env is not None else os.environ

    def load(self) -> dict[str, str]:
        active_key = self.prefix + "ACTIVE_KID"
        result: dict[str, str] = {}
        for key, value in self.env.items():
            if key.startswith(self.prefix) and key != active_key and value:
                result[key[len(self.prefix):].lower()] = value
        return result

    def active_kid(self) -> str | None:
        return self.env.get(self.prefix + "ACTIVE_KID")


class SecretRing:
    """多版本密钥环，支持轮换后旧 token 继续验签。"""

    def __init__(self, secrets: Mapping[str, str] | None = None,
                 active_kid: str | None = None) -> None:
        self._secrets: dict[str, str] = dict(secrets or {})
        if active_kid is not None and active_kid not in self._secrets:
            raise ValueError(f"active_kid={active_kid} 不在密钥环中")
        self._active_kid = active_kid or (next(iter(self._secrets), None)
                                          if self._secrets else None)
        self._counter = len(self._secrets)

    @classmethod
    def from_provider(cls, provider: SecretsProvider) -> "SecretRing":
        """从任意 SecretsProvider 构建密钥环。"""
        return cls(provider.load(), provider.active_kid())

    @property
    def active_kid(self) -> str | None:
        return self._active_kid

    @property
    def kids(self) -> list[str]:
        return list(self._secrets)

    def add(self, kid: str, secret: str) -> None:
        if not kid or not secret:
            raise ValueError("kid 与 secret 不能为空")
        self._secrets[kid] = secret
        if self._active_kid is None:
            self._active_kid = kid

    def revoke(self, kid: str) -> bool:
        """撤销某版本；若它是当前版本则切换到剩余任一版本。"""
        if kid not in self._secrets:
            return False
        del self._secrets[kid]
        if self._active_kid == kid:
            self._active_kid = next(iter(self._secrets), None)
        return True

    def rotate(self, new_kid: str | None = None,
               secret: str | None = None) -> str:
        """生成并启用新版本；旧版本保留用于验签。

        未指定 ``secret`` 时生成确定性的本地派生密钥（便于离线测试）。
        """
        self._counter += 1
        kid = new_kid or f"k{self._counter}"
        while kid in self._secrets:
            self._counter += 1
            kid = f"k{self._counter}"
        value = secret or hashlib.sha256(
            f"{kid}:{self._counter}:derived".encode("utf-8")
        ).hexdigest()
        self.add(kid, value)
        self._active_kid = kid
        return kid

    def sign(self, payload: str | bytes | Mapping[str, Any],
             kid: str | None = None) -> str:
        """用指定（默认当前）密钥对 payload 签名，返回 ``kid.body.sig``。"""
        key_id = kid or self._active_kid
        if key_id is None or key_id not in self._secrets:
            raise ValueError("没有可用的签名密钥")
        if isinstance(payload, bytes):
            raw = payload
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = json.dumps(payload, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        body = _b64(raw)
        signature = _b64(hmac.new(
            self._secrets[key_id].encode("utf-8"),
            body.encode("ascii"), hashlib.sha256,
        ).digest())
        return f"{key_id}.{body}.{signature}"

    def verify(self, token: str) -> str | None:
        """验签并返回原始 payload 文本；未知 kid / 签名不符返回 None。"""
        try:
            kid, body, signature = token.split(".", 2)
        except (ValueError, AttributeError):
            return None
        secret = self._secrets.get(kid)
        if secret is None:
            return None
        expected = _b64(hmac.new(
            secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256,
        ).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            return _unb64(body).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return None


__all__ = ["SecretRing", "SecretsProvider", "EnvSecretsProvider"]
