"""从 YAML 加载 flow 配置。

支持一次加载多个文件（user_flows.yml + system_flows.yml），
后加载的文件不会覆盖先加载的 flow，避免同名流程互相踩踏。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.task.flow_models import (
    ActionFlowStep,
    CollectSlotStep,
    ConditionalLink,
    EndFlowStep,
    FallbackLink,
    Flow,
    FlowsList,
    FlowSlot,
    FlowStep,
    FlowStepLink,
    FlowStepType,
    ResponseDefinition,
    SlotValidation,
    StartFlowStep,
    StaticLink,
)


class FlowLoader:
    def load_many(self, paths: list[str | Path]) -> FlowsList:
        flows: list[Flow] = []
        slots: dict[str, FlowSlot] = {}

        for path in paths:
            file_path = Path(path)
            if not file_path.exists():
                raise FileNotFoundError(f"flow 配置文件不存在: {file_path}")
            raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}

            for name, definition in (raw.get("slots") or {}).items():
                if name not in slots:
                    slots[name] = self._parse_slot(name, definition)

            for flow_id, definition in (raw.get("flows") or {}).items():
                if any(existing.id == flow_id for existing in flows):
                    continue
                flows.append(self._parse_flow(flow_id, definition, slots))

        return FlowsList(flows=flows, slots=slots)

    # ------------------------------------------------------------------ 解析
    @staticmethod
    def _parse_slot(name: str, definition: dict[str, Any] | None) -> FlowSlot:
        data = definition or {}
        return FlowSlot(
            name=name,
            type=str(data.get("type") or "any"),
            label=str(data.get("label") or ""),
            description=str(data.get("description") or ""),
        )

    def _parse_flow(
        self,
        flow_id: str,
        definition: dict[str, Any],
        global_slots: dict[str, FlowSlot],
    ) -> Flow:
        steps = [self._parse_step(item) for item in definition.get("steps") or []]
        return Flow(
            id=flow_id,
            name=definition.get("name"),
            description=str(definition.get("description") or ""),
            steps=steps,
            slots=self._infer_slots(flow_id, definition, steps, global_slots),
        )

    @staticmethod
    def _infer_slots(
        flow_id: str,
        definition: dict[str, Any],
        steps: list[FlowStep],
        global_slots: dict[str, FlowSlot],
    ) -> list[FlowSlot]:
        """flow 自己没声明 slots 时，从 collect step 反推它用到哪些槽位。

        这样配置只需要在顶层写一次槽位定义，flow 里重复写一遍是多余的；
        而提示词里又需要知道每条 flow 需要哪些参数，所以在这里补齐。
        """
        if definition.get("slots"):
            result: list[FlowSlot] = []
            for item in definition["slots"]:
                if isinstance(item, str):
                    result.append(
                        global_slots.get(item)
                        or FlowSlot(name=item, label=item, description=item)
                    )
                elif isinstance(item, dict):
                    name = item.get("name", "")
                    result.append(
                        FlowSlot(
                            name=name,
                            type=item.get("type", "any"),
                            label=item.get("label", ""),
                            description=item.get("description", ""),
                        )
                    )
            return result

        names: list[str] = []
        for step in steps:
            if isinstance(step, CollectSlotStep) and step.slot_name:
                if step.slot_name not in names:
                    names.append(step.slot_name)
        # start step 的条件跳转里也可能引用槽位（如 similar_product_recommendation）
        for step in steps:
            for link in step.next:
                if isinstance(link, ConditionalLink):
                    for slot_name in global_slots:
                        if slot_name in link.condition and slot_name not in names:
                            names.append(slot_name)

        return [
            global_slots.get(name) or FlowSlot(name=name, label=name, description=name)
            for name in names
        ]

    def _parse_step(self, item: dict[str, Any]) -> FlowStep:
        step_type = FlowStepType(str(item.get("type") or "action").lower())
        common = {
            "id": str(item.get("id") or ""),
            "type": step_type,
            "next": self._parse_links(item.get("next")),
            "description": str(item.get("description") or ""),
        }

        if step_type is FlowStepType.START:
            return StartFlowStep(**common)
        if step_type is FlowStepType.COLLECT:
            return CollectSlotStep(
                **common,
                slot_name=str(item.get("slot_name") or ""),
                response=ResponseDefinition.from_dict(item.get("response")),
                validation=SlotValidation.from_dict(item.get("validation")),
            )
        if step_type is FlowStepType.END:
            return EndFlowStep(**common)
        return ActionFlowStep(
            **common,
            action=str(item.get("action") or ""),
            args=item.get("args") if item.get("args") is not None else {},
        )

    @staticmethod
    def _parse_links(raw: Any) -> list[FlowStepLink]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [] if not raw.strip() else [StaticLink(target=raw)]
        if isinstance(raw, dict):
            raw = [raw]

        links: list[FlowStepLink] = []
        for item in raw:
            if isinstance(item, str):
                links.append(StaticLink(target=item))
                continue
            if not isinstance(item, dict):
                continue
            if "if" in item and "then" in item:
                links.append(ConditionalLink(target=str(item["then"]), condition=str(item["if"])))
            elif "else" in item:
                links.append(FallbackLink(target=str(item["else"])))
            elif "then" in item:
                links.append(StaticLink(target=str(item["then"])))
        return links
