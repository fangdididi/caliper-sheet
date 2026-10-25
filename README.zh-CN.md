# caliper-sheet（卡尺图纸）

[English](README.md) | **中文**

**把一个实物零件认真量一次，得到一张靠得住的图纸。**

caliper-sheet 是一个智能体技能，适用于 Claude Code、Codex、Cursor 以及其他能读取 `SKILL.md` 的智能体。它带你从桌上的一个实物（断掉的卡扣、层板支架、旋钮、垫片）出发，得到一份经过校验的测量记录和一页按真实比例的图纸，3D 打印机、加工厂或卖家都能照着做。

![示例图纸：层板支架片的俯视、主视、右视图，比例 1:1](examples/shelf-bracket.png)

## 为什么需要它

复刻零件失败，通常是因为一些小事：卡尺斜着只读了一次；需要精确到 0.1 mm 的地方用了直尺；位置一段接一段地量，误差越积越大；英制零件被换算成毫米后取整；看不见的尺寸被人估了一个数。caliper-sheet 在动材料之前把这些问题逐一抓出来，最后再做一次纸面验证：按 100% 打印图纸，把零件放上去看一看。

## 功能

- **零件卡与基准。** 先弄清零件装在哪里、哪些面是关键，再从基准面量位置，而不是链式累加。
- **带作用的尺寸代号。** 每个尺寸有代号（`L1`、`X2`、`D1` 等）和作用：`mating` 配合 ±0.1 mm、`clearance` 间隙 ±0.3 mm、`free` 自由 ±0.5 mm。所有检查都按作用来判断。
- **每个尺寸读三次。** 脚本取中位数；读数不一致时标 `REMEASURE`，精密尺寸用了直尺时标 `TOOL_TOO_COARSE`，配合尺寸读数不足时标 `FEW_READINGS`。
- **推导尺寸用公式。** `X2 = X1 + P1`、`Y1 = W1 / 2`，安全求值并按依赖顺序计算，循环引用和未知代号都会被拒绝。
- **尺寸链闭合检查。** 把一串尺寸相加，与总尺寸比较，得出 `CLOSES`、`LOOSE` 或 `CLOSURE_FAIL`。
- **只提示不篡改。** 可能的英制尺寸（12.70 就是 1/2 英寸）、标准公制通孔和螺纹底孔只作为建议，绝不自动套用。
- **未知就是未知。** `[TBD]` 尺寸会一路传递到公式和结论里，绝不被填上一个猜测值。
- **一个结论。** `READY`、`DRAFT_ONLY` 或 `MEASURE_AGAIN`（退出码 2），智能体或脚本可以据此在出图前停下。
- **真实比例的 SVG 图纸。** 第三角投影的俯视、主视、右视图，代号标注的尺寸线，数值表，标题栏和 50 mm 校验尺。放得下就是 1:1，大零件自动缩小，小零件自动放大。
- **纸面验证。** 打印出来，确认图纸与实物一致。
- **零依赖。** 一个 Python 3 文件，只用标准库，附 54 个测试。

## 安装

**Claude Code**

```bash
git clone https://github.com/fangdididi/caliper-sheet ~/.claude/skills/caliper-sheet
```

**Codex**

```bash
git clone https://github.com/fangdididi/caliper-sheet ~/.codex/skills/caliper-sheet
```

**Cursor 及其他智能体。** 把仓库克隆到项目里（例如 `.cursor/skills/caliper-sheet` 或 `skills/caliper-sheet`），让智能体读取 `SKILL.md`（英文）或 `SKILL.zh-CN.md`（中文）。

**claude.ai / Claude 桌面版。** 把文件夹打包成 zip，在应用的技能设置里上传。

辅助脚本只需要 Python 3.8 或更新版本。

## 使用方法

对智能体说类似这样的话：

> 我家放层板的塑料支架断了，我有一把卡尺，帮我量一下好 3D 打印一个新的。

> 这个孔是多大？这个老零件是不是英制的？

智能体会问几个问题，帮你定好基准，把每个尺寸的三次读数记进 `part.json`，然后运行：

```bash
python3 scripts/partsheet.py check part.json        # 标记、尺寸链、结论
python3 scripts/partsheet.py svg part.json -o sheet.svg
python3 scripts/partsheet.py table part.json        # Markdown 尺寸表
```

### 最小的 `part.json`

```json
{
  "part": {"id": "PART-001", "name": "垫块", "units": "mm", "purpose": "print"},
  "dims": [
    {"code": "L1", "name": "长度", "role": "clearance", "readings": [40.02, 40.00, 40.04]},
    {"code": "W1", "name": "宽度", "role": "clearance", "readings": [12.00, 12.02, 11.98]},
    {"code": "T1", "name": "厚度", "role": "mating", "readings": [5.00, 5.02, 5.00]},
    {"code": "D1", "name": "螺栓孔", "role": "mating", "readings": [4.50, 4.52, 4.48]},
    {"code": "X1", "name": "孔距基准 A", "role": "mating", "formula": "L1 / 2"},
    {"code": "Y1", "name": "孔距基准 B", "role": "mating", "formula": "W1 / 2"}
  ],
  "body": {"L": "L1", "W": "W1", "T": "T1"},
  "features": [{"kind": "hole", "d": "D1", "x": "X1", "y": "Y1", "through": true}]
}
```

## 示例

- `examples/shelf-bracket.json`：双孔支架片。结论 `READY`，长度方向的尺寸链误差 0.04 mm，闭合；孔径符合 M3 中等配合通孔。图纸见 `examples/shelf-bracket.svg`。
- `examples/knob-insert.json`：磨损的旋钮内衬。结论 `MEASURE_AGAIN`：轴孔读数极差 0.33 mm，一个配合平面尺寸未知，外形尺寸正好是 3/4 英寸和 1/2 英寸。

检查输出片段：

```text
D1         3.42  ±0.1  mating    measured screw hole
      ~ LOOKS_LIKE: M3 clearance (normal)
chain length along hole row: CLOSES  sum 80 vs L1 80.04, off by -0.04 (rss 0.6, worst 1)
VERDICT READY
```

## 文件结构

```text
caliper-sheet/
├── SKILL.md                 技能说明（英文）
├── SKILL.zh-CN.md           技能说明（中文）
├── README.md                英文 README
├── README.zh-CN.md          本文件
├── LICENSE                  MIT
├── scripts/
│   └── partsheet.py         check、table、svg 三个命令
├── examples/
│   ├── shelf-bracket.json   READY 示例
│   ├── shelf-bracket.svg    对应的真实比例图纸
│   ├── shelf-bracket.png    预览图
│   └── knob-insert.json     MEASURE_AGAIN 示例
└── tests/
    └── test_partsheet.py    54 个测试（python3 -m unittest discover -s tests）
```

## 许可证

MIT © fangdididi
