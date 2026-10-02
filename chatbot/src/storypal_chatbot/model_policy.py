"""StoryPal 的 Luna 型号策略；可选型号不等于自动回退链。"""

DEFAULT_MODEL = "openai-codex/gpt-6-luna"
LEGACY_MODEL = "openai-codex/gpt-5.6-luna"
ALLOWED_MODELS = frozenset({DEFAULT_MODEL, LEGACY_MODEL})
LUNA_PRESET = "storypal-luna"
LEGACY_LUNA_PRESET = "storypal-luna-5-6"
