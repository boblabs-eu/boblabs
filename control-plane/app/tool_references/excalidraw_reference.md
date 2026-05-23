# Excalidraw Tool Reference

## Overview
Create diagrams by providing a JSON array of Excalidraw elements. The tool saves a `.excalidraw` file, renders a PNG, and uploads to excalidraw.com for a shareable link.

## Element Format

### Required Fields (all elements)
`type`, `id` (unique string), `x`, `y`, `width`, `height`

### Defaults (applied automatically)
- `strokeColor`: `"#1e1e1e"`
- `backgroundColor`: `"transparent"`
- `fillStyle`: `"solid"`
- `strokeWidth`: `2`
- `roughness`: `1`
- `opacity`: `100`

## Element Types

**Rectangle**: `{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100, "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid" }`

**Ellipse**: `{ "type": "ellipse", "id": "e1", "x": 100, "y": 100, "width": 150, "height": 150 }`

**Diamond**: `{ "type": "diamond", "id": "d1", "x": 100, "y": 100, "width": 150, "height": 150 }`

### CRITICAL: Labeled Shapes (Container Binding)
> **WARNING:** Do NOT use `"label": { "text": "..." }` — this does NOT exist in Excalidraw and will be silently ignored. Always use container binding.

Shape needs `boundElements`, text needs `containerId`:
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 80,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] },
{ "type": "text", "id": "t_r1", "x": 105, "y": 120, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```

### Labeled Arrow
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 200, "height": 0,
  "points": [[0,0],[200,0]], "endArrowhead": "arrow",
  "boundElements": [{ "id": "t_a1", "type": "text" }] },
{ "type": "text", "id": "t_a1", "x": 370, "y": 130, "width": 60, "height": 20,
  "text": "connects", "fontSize": 16, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "a1", "originalText": "connects", "autoResize": true }
```

### Standalone Text (titles only)
```json
{ "type": "text", "id": "t1", "x": 150, "y": 30, "text": "My Title", "fontSize": 28,
  "fontFamily": 1, "strokeColor": "#1e1e1e", "originalText": "My Title", "autoResize": true }
```

### Arrow with Bindings
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] } }
```
fixedPoint: top=[0.5,0], bottom=[0.5,1], left=[0,0.5], right=[1,0.5]

## Color Palette

| Use | Fill | Hex |
|-----|------|-----|
| Primary / Input | Light Blue | `#a5d8ff` |
| Success / Output | Light Green | `#b2f2bb` |
| Warning / External | Light Orange | `#ffd8a8` |
| Processing / Special | Light Purple | `#d0bfff` |
| Error / Critical | Light Red | `#ffc9c9` |
| Notes / Decisions | Light Yellow | `#fff3bf` |
| Storage / Data | Light Teal | `#c3fae8` |

Stroke colors: Blue `#4a9eed`, Amber `#f59e0b`, Green `#22c55e`, Red `#ef4444`, Purple `#8b5cf6`

## Sizing & Font Rules
- Min shape size: 120x60 for labeled shapes
- Min font: 16 for body, 20 for titles, 14 for annotations (never below 14)
- Leave 20-30px gaps between elements
- Always include `fontFamily: 1` on all text elements

## Z-Order
Array order = z-order (first = back, last = front).
Emit: background zones → shape → its bound text → its arrows → next shape.

## Dark Mode
Set `dark_mode: "true"`. Use dark fills (#1e3a5f, #1a4d2e, #2d1b69) and light text (#e5e5e5).
