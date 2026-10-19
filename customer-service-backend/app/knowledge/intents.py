"""知识意图表：系统"能回答哪几类问题"。

这张表同时是两件事：
  1. TurnPlanner 的候选清单（提示词里会把它塞给模型，模型只能从里面选）
  2. KnowledgeHandler 的路由表（意图 -> 查哪些数据源）

新增一类知识，只需要在这里加一条，然后配一个 provider。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class KnowledgeIntent:
    id: str
    description: str
    provider_ids: list[str] = field(default_factory=list)
    # 该意图是否必须先有聚焦对象；"product" 表示必须有聚焦商品
    requires_object: str | None = None


KNOWLEDGE_INTENTS: dict[str, KnowledgeIntent] = {
    "product_info": KnowledgeIntent(
        id="product_info",
        description="商品信息咨询，例如价格、参数、材质、卖点、库存",
        provider_ids=["api.product"],
        requires_object="product",
    ),
    "order_info": KnowledgeIntent(
        id="order_info",
        description="订单信息咨询，例如这笔订单买了什么、金额、收货信息、物流进度",
        provider_ids=["api.order"],
        requires_object="order",
    ),
    "refund_policy": KnowledgeIntent(
        id="refund_policy",
        description="退款政策咨询，例如退款条件、退款时效、退款到账时间",
        provider_ids=["faq.default", "rag.default"],
    ),
    "return_policy": KnowledgeIntent(
        id="return_policy",
        description="退货政策咨询，例如七天无理由、退货条件、退货运费谁承担",
        provider_ids=["faq.default", "rag.default"],
    ),
    "shipping_policy": KnowledgeIntent(
        id="shipping_policy",
        description="配送政策咨询，例如发货时效、配送范围、运费规则、能否指定快递",
        provider_ids=["faq.default", "rag.default"],
    ),
    "platform_rule": KnowledgeIntent(
        id="platform_rule",
        description="平台规则咨询，例如发票开具、价保规则、优惠券使用、账号与售后规则",
        provider_ids=["faq.default", "rag.default"],
    ),
    "general_ecommerce_info": KnowledgeIntent(
        id="general_ecommerce_info",
        description="电商通用信息咨询，例如支付方式、下单流程、会员权益",
        provider_ids=["faq.default", "rag.default"],
    ),
}
