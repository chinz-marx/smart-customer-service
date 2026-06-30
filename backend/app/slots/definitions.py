from __future__ import annotations

from app.configs.loader import load_runtime_config
from app.slots.schemas import IntentSlotConfig


# 槽位定义统一从 app/configs/intents.yaml 读取。
# 保留这个模块，是为了让 SlotManager 不关心配置文件怎么加载。
INTENT_SLOT_CONFIGS: dict[str, IntentSlotConfig] = load_runtime_config().slot_configs