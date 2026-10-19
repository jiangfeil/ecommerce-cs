"""模拟电商业务服务客户端。

客服系统自己不存订单，所有实时业务数据都通过这里向中台要。
把 HTTP 细节收在一个类里，上层 Provider / Action 只面对有语义的方法名。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class CommerceApiError(RuntimeError):
    """中台接口调用失败。

    除了消息，还保留 HTTP 状态码和业务 detail，
    这样上层才能区分"订单不存在(404)"、"已有退款(409)"、"状态不支持(400)，
    进而给出不同的话术，而不是把后端报错原样抛给用户。
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class CommerceClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
            # 中台是本机服务，绝不能走系统代理，
            # 否则请求会被当成代理请求转发，路径变成 http%3A//... 而 404
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ 内部
    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CommerceApiError(f"请求 {path} 失败: {exc}") from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = str(payload.get("detail") or "")
            except Exception:  # noqa: BLE001
                detail = response.text[:200]
            raise CommerceApiError(
                f"{path} 返回 {response.status_code}: {detail or response.text[:120]}",
                status_code=response.status_code,
                detail=detail,
            )

        payload = response.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ------------------------------------------------------------------ 用户
    async def get_user_orders(self, user_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/users/{user_id}/orders")

    async def get_user_products(self, user_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/users/{user_id}/products")

    # ------------------------------------------------------------------ 订单
    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/orders/{order_id}")

    async def get_order_status(self, order_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/orders/{order_id}/status")

    async def get_logistics(self, order_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/orders/{order_id}/logistics")

    # ------------------------------------------------------------------ 商品
    async def get_product(self, product_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/products/{product_id}")

    # -------------------------------------------------------------- 订单操作
    async def urge_shipping(
        self,
        order_id: str,
        submitted_by: str = "system",
        note: str = "用户希望尽快发货",
    ) -> dict[str, Any] | None:
        return await self._request(
            "POST",
            f"/orders/{order_id}/shipping-reminders",
            json={"submitted_by": submitted_by, "note": note},
        )

    async def apply_refund(
        self,
        order_id: str,
        reason: str,
        submitted_by: str = "system",
    ) -> dict[str, Any] | None:
        return await self._request(
            "POST",
            f"/orders/{order_id}/refund-applications",
            json={"submitted_by": submitted_by, "reason": reason},
        )


_commerce_client: CommerceClient | None = None


def init_commerce_client() -> CommerceClient:
    global _commerce_client
    _commerce_client = CommerceClient(
        base_url=settings.commerce_api_base_url,
        timeout=settings.commerce_api_timeout,
    )
    return _commerce_client


def get_commerce_client() -> CommerceClient:
    global _commerce_client
    if _commerce_client is None:
        _commerce_client = init_commerce_client()
    return _commerce_client


async def close_commerce_client() -> None:
    global _commerce_client
    if _commerce_client is not None:
        await _commerce_client.close()
        _commerce_client = None
