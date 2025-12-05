# Display module API

This document defines the shared contract for modules loaded by the Dumb Smart Display. It is intended to be a concise reference when creating or updating modules.

## Module shape

Each module should expose a `Module` class that follows the [`DisplayModule` protocol](../app/core/module_interface.py):

- **name**: Human-readable identifier used for navigation and logs.
- **`__init__(config, fonts)`**: Constructor receives a module-specific `config` mapping and a shared `fonts` dictionary.
- **`render(width, height, **kwargs) -> PIL.Image.Image`**: Produce the frame for the current cycle. The display driver supplies the `width` and `height`.
- **`tick() -> None`**: Perform background or periodic work (e.g., refreshing cached data). This is called for all modules, not just the active one.
- **`handle_button(event: str) -> None`**: React to logical button events (`"prev"`, `"next"`, or `"action"`).

### Optional hooks

- **`refresh_interval() -> Optional[int]`**: Hint (in seconds) for how often the module would like to refresh. Return `None` to defer to the default cadence.
- **`supported_layouts() -> Sequence[LayoutPreset]`**: Advertise the layout variants that the module knows how to render. If not implemented, consumers should assume only the `"full"` preset is available.

If you prefer not to reimplement optional hooks, inherit from `BaseDisplayModule` to get default implementations for `refresh_interval` and `supported_layouts`.

## Layout presets

Layout presets live alongside the protocol in [`app/core/module_interface.py`](../app/core/module_interface.py) and capture the shapes shown in the planning reference image. Presets are expressed as `LayoutPreset` dataclasses built from a simple grid definition:

```python
LayoutPreset(
    name="full",
    columns=4,
    rows=2,
    slots=(LayoutSlot("main", colspan=4, rowspan=2),),
    description="Single canvas taking the full display area.",
)
```

A preset describes:

- **name**: A stable identifier.
- **columns / rows**: Grid dimensions the slots map to.
- **slots**: Ordered `LayoutSlot` entries with a `key`, `colspan`, and `rowspan`. The order lets consumers assign content deterministically.
- **description**: Human-readable summary for documentation or UI hints.
- **compact**: Boolean flag to indicate denser layouts suitable for smaller displays.

### Available presets

`DEFAULT_LAYOUTS` currently includes the following options:

| Name | Description | Columns x Rows | Slots | Compact |
| --- | --- | --- | --- | --- |
| `full` | Single canvas taking the full display area. | 4 x 2 | 1 | No |
| `wide_left` | Large area on the left with a tall sidebar on the right. | 4 x 2 | 2 | No |
| `wide_right` | Large area on the right with two stacked panels on the left. | 4 x 2 | 3 | No |
| `three_column` | Three columns with mixed tall and short cards. | 3 x 2 | 5 | No |
| `quads` | Four even quadrants for equally weighted content. | 2 x 2 | 4 | No |
| `compact_quads` | Narrow header with stacked compact cards beneath. | 2 x 3 | 5 | Yes |
| `striped_rows` | Mixed stripes with a wide header row and smaller tiles below. | 3 x 2 | 5 | Yes |

Modules that support multiple layouts should order them by preference in `supported_layouts`, with the most preferred first. Consumers can use the `compact` flag to pick denser options when screen real estate is limited.
