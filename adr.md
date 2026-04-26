# ADR v1

### screen scaling (add)
- add scaling to screen
- user can define screen size beforehand, then run program like normal
- render engine have one more job: resizing by multiply constant
- image resizing: scale image IN the software compiler side instead
  - reduce the scaling work in hardware
  - but increase storage use and software complexity (because img is bitmap)

### physics pipeline engine (drop)
- for complex physic interaction that require multiple operation, use micro-instruction to seperate hardware
- good for define custom collision, custom move, scaling function
- require seperate call ISA, add unnessesary complexity
- integrade to pipeline might be hard, either
  - blocking function call: this module might be a new hot path, better to just add custom ISA
  - async: pipeline nightmare

### basic cpu pipeline (drop)
- add basic pipeline: out-of-order execution
- tradeoff is bad
  - gain maximum speed in theory
  - but increase complexity significantly
- not even mention branch prediction and the hardware aleady complicated af

### bram-only ISA (drop)
- remove register-base command entirely (except for jump-related)
- look easier, stage is clear
- took lot more cycle (2/5 stage is not possible), complex inline math take a lot more 
- the variable is mostly one-way write from cpu to bram. Multiple fetch from bram might be unnessessary

### register flush system (drop)
- since the cpu is strictly 60 fps and halt after rendered. We can do the "fetch, wait for finished, then flush"
- at start of frame, cpu fetch everything it need from bram into register
- compute inside register including read, write, etc.
- at the end of the frame, additional mdule "flush" everything into bram
- if register is full, cpu can force flush first
- very good for repeating calculation and cpu didn't have to do much
- must have seperate "flusher" component, intrducing 2 master problem
- interrupt management might not be that clean
- register must have sidecar (writeback addr and bit), futher complicated the design

### compiler manual flush (apply)
- previous adr is too complicated, so just move complexity to compiler.
- compiler must manage which to pull, which to STORE
  - this problem will be hard if cpu run at more speed than render
  - but since the cpu always wait for render, we have plenty of time. So just let cpu store one by one
  - we also don't need writeback inbetween (if register is not full)
- much better development and no clock problem, no sidecar anything
- more complex compiler

### pure 5 stage to 2/5 stage (apply)
- since the hot path usually be the path from bram to cpu, register-based operation can jump to execute directly while add and writeback at the same time
- faster cpu (register operation need 2 cycle)
- don't know if the execution stage will become the hot path instead
  - will change to 3 stage if 2 is not good

### add real one-level deep function (apply)
- normal function call in program
- easy to implement in hardware: just save pc, jump, then jump back
- can be good for interrupt (rather than seperate thing, just create a function and hook up key)
- might be unnessesary complexity
- considering inline way (not sure)

### interrupt flag before halt (apply)
- if input is apply, raise flag KEY_PRESS, then wait for next non-halt command
- use normal function
- previuosly consider checking interrupt in the halt stage, but might have very small edge case: interrupt while rendering

### fifo-based command stream to render engine (drop)
- normally, the render flow is
  - cpu calculate everything -> cpu save & send render() command -> render take everything and render in order -> dma
- fifo can be intruduce inbetween cpu and render
  - rather than commit -> render, use fifo and stream command instead
  - some shape that have this properties can be rendered before real render() commit
    - require no calculation futher in the chain
    - AND no intterupt can change
- increase the speed of overall pipeline
- additional fifo, can get overwhelem, block cpu?
- intruduce z component problem
  - component need to be either send in z order or small rearrange buffer. painful 
  - can be solve by compiler rearrange (maybe hard)
- maybe not so good tradeoff

### z component (apply)
- add additional z component into bram structure
- make the render engine run n times for n level
- realisticly require n = 2 only
- dynamic z is now possible
- but make the render part n time longer, but it might fast enough. Let's try

### static shape overwrite (apply)
- at first, bram is hard seperate into static (background) shape and dynamic shape
- static shape sits in the bram forever, and render engine need to know where to start (take more cycle to start)
- to solve, let cpu manage everyhting: static render, shape override, and compute
- remove "where to start" from render engine entirely. become even more dumb
- remove unnessesary shape at runtime

### screen clearing (apply)
- at first, use compiler-based shape redraw, hard af
- change to complete ddr clear
  - triggering at the start of cycle, by render engine. on it's own
  - render flag only signal "bram ready". render engine can wait for itself to finished first
- very easy to implement
- additional ddr bandwidth

### COL and MOVS ISA (?)
- COL for collition detecion
- MOVS for "move entire shape"
- not sure should be implement
