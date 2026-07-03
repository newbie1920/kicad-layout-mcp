# kicad-layout-mcp

MCP server cho AI thiết kế schematic và PCB KiCad. AI chỉ mô tả mạch ở mức ngữ nghĩa (linh kiện, net, khối chức năng); toàn bộ hình học (vị trí, đi dây, nhãn) do engine thuật toán đảm nhận. **AI không bao giờ được đưa tọa độ tuyệt đối.**

## Nguyên tắc

- Tool ít, mức cao, khai báo.
- Không tọa độ trong input.
- Validate sớm, lỗi rõ ràng để AI tự sửa.
- `generate_project` chạy toàn bộ pipeline một phát.

## Cài đặt

```bash
cd kicad-layout-mcp
pip install -e .
```

## Cấu hình MCP

### Claude Desktop

Edit `%APPDATA%\Claude\settings.json`:

```json
{
  "mcpServers": {
    "kicad-layout": {
      "command": "python",
      "args": ["-m", "kicad_layout_mcp.server"]
    }
  }
}
```

### Cursor / v0

Thêm vào `.cursor/mcp.json` hoặc cấu hình MCP server:

```json
{
  "mcpServers": {
    "kicad-layout": {
      "command": "python",
      "args": ["-m", "kicad_layout_mcp.server"]
    }
  }
}
```

## Các tool MCP

| Tool | Chức năng |
|------|-----------|
| `create_circuit` | Tạo mạch mới |
| `add_component` | Thêm linh kiện (ref, part, value, block) |
| `connect` | Nối danh sách `(ref, pin)` vào net |
| `list_library` | Liệt kê part/footprint có sẵn |
| `validate_circuit` | Kiểm tra netlist |
| `generate_project` | Chạy pipeline → `.kicad_pro/.kicad_sch/.kicad_pcb` |
| `preview` | Render SVG schematic/PCB |
| `get_report` | BOM, track length, via, DRC |

## Ví dụ

AI gọi tuần tự:

```json
{"name": "create_circuit", "arguments": {"name": "led_button", "description": "LED + resistor + button"}}
{"name": "add_component", "arguments": {"circuit_name": "led_button", "ref": "R1", "part": "R", "value": "1k", "block": "io"}}
{"name": "add_component", "arguments": {"circuit_name": "led_button", "ref": "D1", "part": "LED", "value": "RED", "block": "io"}}
{"name": "add_component", "arguments": {"circuit_name": "led_button", "ref": "SW1", "part": "SW_PUSH", "block": "io"}}
{"name": "add_component", "arguments": {"circuit_name": "led_button", "ref": "J1", "part": "CONN_1x02", "block": "io"}}
{"name": "connect", "arguments": {"circuit_name": "led_button", "net": "VCC", "pins": [{"ref": "J1", "pin": "1"}, {"ref": "R1", "pin": "1"}]}}
{"name": "generate_project", "arguments": {"circuit_name": "led_button", "output_dir": "out/led_button"}}
```

## Kiến trúc

```
kicad_layout_mcp/
├── server.py           # FastMCP server
├── pipeline.py         # generate_project
├── core/
│   ├── circuit.py      # Mô hình mạch trung gian
│   ├── sexpr.py        # S-expression writer
│   └── validate.py     # Netlist validation
├── library/
│   └── parts.py        # Symbol + footprint nhúng
├── schematic/
│   ├── placer.py       # Block layout, BFS, shelf-pack
│   ├── router.py       # Manhattan A*, power symbols, net labels
│   ├── labeler.py      # Reference/value placement
│   └── writer.py       # .kicad_sch
├── pcb/
│   ├── placer.py       # Cluster + simulated annealing
│   ├── router.py       # 2-layer Manhattan autorouter
│   ├── silkscreen.py   # Silk label placement
│   ├── drc.py          # Clearance, overlap checks
│   └── writer.py       # .kicad_pcb
└── preview/
    └── render.py       # SVG schematic/PCB
```

## Test

```bash
python -m pytest tests/test_end_to_end.py -v
```

3 mạch mẫu: LED+button, AMS1117+ESP32, LM358 preamp — đều qua DRC nội bộ và parse được bằng `kiutils`.

## Giới hạn

- Autoroute 2 lớp phù hợp mạch nhỏ–vừa (~100 linh kiện).
- Thư viện nhúng ~37 part cơ bản; part lạ cần bổ sung.
- RF/tốc độ cao vẫn cần người tinh chỉnh.
