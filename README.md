# soc-render-engine

A custom FPGA-based graphics SoC with a purpose-built high-level language and compiler.

## Overview

This project is a full-stack hardware/software co-design — a complete graphics accelerator
SoC targeting FPGA, paired with a domain-specific language (DSL) and compiler that
compiles down to a custom 16-instruction ISA.

The goal: write simple, readable scene descriptions in a high-level language, compile
them, and have the hardware render and display animated graphics over HDMI at 60 fps.

## Architecture

The SoC consists of these main components:

- **CPU** — 32-bit, 16-register, multi-stage (2/5-stage hybrid), 16-instruction ISA
- **BRAM** — stores program, integer variables, and shape descriptors
- **Render Engine** — render controller + renderer, handles static/dynamic layer separation
- **DDR** — frame buffers + image storage, 8 MiB blocks per image (1024×768×4 byte)
- **Image Storer** — loads bitmap images into DDR at startup
- **HDMI Interface** — ping-pong double buffering synced to vsync
- **Controller** — top-level state machine coordinating all subsystems
- **UART** — program loading at startup

```
UART → Controller ↔ CPU ↔ BRAM
                 ↔ Render Controller ↔ Renderer ↔ DDR ↔ HDMI
                 ↔ Image Storer ↔ DDR
```

## Language & Compiler

Programs are written in a custom DSL with a Lark-based grammar. The language supports:

- Typed variables: `int`, `shape` (rect/triangle), `image`
- Static and dynamic render layers
- Control flow: `if`, `else`, `while`, `break`, `label`
- Special hardware calls: `render()`, `halt()`, `wait_for_button()`, `img()`
- Interrupt hooks via `control` block

Example:
```
int { h = 700  delta_h = 1 }
static  { background = Rect(0, 0, 768, 1024, img=background_img) }
dynamic { player = Tri(0, 0, 768, 1024, anchor=top_left, color=[r,g,b]) }

label START
while (h > 400) {
    h = h - delta_h
    player.h0 = h
    render()
}
halt()
```

The compiler translates this into binary targeting the custom ISA and manages register
allocation, variable layout in BRAM, and static shape ordering for the render engine.

The high level langauge name is suchad

## ISA

16 instructions, 32-bit fixed width, big-endian:

| Opcode | Mnemonic | Description |
|--------|----------|-------------|
| 0000 | NOOP | No operation |
| 0001 | LDI | Load 24-bit immediate |
| 0010 | LD | Load from BRAM |
| 0011 | ST | Store to BRAM |
| 0100 | MOV | Register copy |
| 0101 | ADD | Addition |
| 0110 | SUB | Subtraction |
| 0111 | AND | Bitwise AND |
| 1000 | OR | Bitwise OR |
| 1001 | JMP | Unconditional jump |
| 1010 | CMP | Compare (sets flags) |
| 1011 | BEQ | Branch if equal |
| 1100 | BGT | Branch if greater |
| 1101 | BLT | Branch if less |
| 1110 | CALL | Special hardware function |

## Status

- [x] Architecture designed
- [x] ISA defined
- [x] DSL grammar defined (Lark)
- [x] Compiler implemented
- [ ] RTL implementation (in progress)
- [ ] Simulation & verification
- [ ] FPGA synthesis

## Design Decisions

See [adr.md](adr.md) for architecture decision records — covering tradeoffs considered
and rejected during design (out-of-order execution, FIFO command streaming, register
flush systems, physics pipeline, and more).
