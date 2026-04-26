import json
import sys
import argparse
import struct

# ==========================================
# 1. CONSTANTS & MEMORY MAP
# ==========================================
# BRAM Layout based on new specs (4-byte words)
# 0-511: Program
# 512-575: Integers
# 576: Static Count
# 577: Dynamic Count
# 578-609: Shape Flags
# 610-641: Shape H0
# 642-673: Shape V0
# 674-705: Shape H1
# 706-737: Shape V1

ADDR_PROGRAM_START  = 0
ADDR_INTS_START     = 512
ADDR_STATIC_CNT     = 576
ADDR_DYNAMIC_CNT    = 577
ADDR_SHAPE_FLAG     = 578
ADDR_SHAPE_H0       = 610
ADDR_SHAPE_V0       = 642
ADDR_SHAPE_H1       = 674
ADDR_SHAPE_V1       = 706

# System Constants (Placed at the end of the Integer block)
# Used for bitwise operations on the "Enable" bit (Bit 26)
ADDR_SYS_CONSTS     = ADDR_INTS_START + 60 

# Opcodes
OP_CODES = {
    0x0: "NOOP", 0x1: "LDI", 0x2: "LD", 0x3: "ST",
    0x4: "MOV", 0x5: "ADD", 0x6: "SUB", 0x7: "AND",
    0x8: "OR",  0x9: "JMP", 0xA: "CMP", 0xB: "BEQ",
    0xC: "BGT", 0xD: "BLT", 0xE: "CALL" 
}

# Instruction Map
OP_LDI, OP_LD, OP_ST   = 0x1, 0x2, 0x3
OP_MOV                 = 0x4
OP_ADD, OP_SUB         = 0x5, 0x6
OP_AND, OP_OR          = 0x7, 0x8 
OP_JMP, OP_CMP         = 0x9, 0xA
OP_BEQ, OP_BGT, OP_BLT = 0xB, 0xC, 0xD
OP_CALL                = 0xE

# Special Function Types (for CALL)
FUNC_IMG           = 0x0
FUNC_RENDER        = 0x1
FUNC_WAIT          = 0x2
FUNC_RENDER_STATIC = 0x3
FUNC_HALT          = 0x4
FUNC_NEW_INTER     = 0x5  # NEW: Register Interrupt

EOF_MARKER = 0xFFFFFFFF

# ==========================================
# 2. COMPILER CLASS
# ==========================================
class RenderEngineCompiler:
    def __init__(self, ast):
        self.ast = ast
        self.program_data = []      # List of (addr, instruction_int, asm_comment)
        self.memory_init = {}       # Map of addr -> value
        self.memory_comments = {}   # Map of addr -> comment string
        
        self.vars = {}          
        self.shapes = {}        
        self.images = {}        
        self.labels = {}        # "LabelName": Address
        self.control_map = []   # List of {"btn": char/code, "label": name}
        
        self.pc = 0             
        self.var_cursor = 0     
        self.shape_cursor = 0   
        self.image_cursor = 0   

    def compile(self):
        # --- 1. Process Header Data ---
        header = self.ast.get("program_header", {})
        self._process_images(header.get("image", []))
        self._process_ints(header.get("int", []))
        self._collect_control(header.get("control", [])) # Collects, doesn't write yet
        
        s_cnt = self._process_shapes(header.get("static", []), is_static=True)
        d_cnt = self._process_shapes(header.get("dynamic", []), is_static=False)
        
        self._write_mem(ADDR_STATIC_CNT, s_cnt, "Static Shape Count")
        self._write_mem(ADDR_DYNAMIC_CNT, d_cnt, "Dynamic Shape Count")

        # --- 2. Inject System Constants ---
        # Bit 26 = 0x04000000 (Enable Bit)
        # Mask   = 0xFBFFFFFF (Inverse)
        self._write_mem(ADDR_SYS_CONSTS, 0x04000000, "SYS: Enable Bit (Bit 26)")
        self._write_mem(ADDR_SYS_CONSTS + 1, 0xFBFFFFFF, "SYS: Enable Mask (~Bit 26)")

        # --- 3. Pass 1: Label Resolution ---
        # We run the generation but discard instructions, just to find where Labels end up.
        self.pc = 0
        self._inject_bootstrap() 
        self._generate_code(pass_number=1)
        
        # --- 4. Pass 2: Final Code Generation ---
        self.pc = 0
        self.program_data = []
        self._inject_bootstrap()
        self._generate_code(pass_number=2)

    # -------------------------------------------------------------------------
    # DATA PROCESSING
    # -------------------------------------------------------------------------
    def _write_mem(self, addr, val, comment=""):
        self.memory_init[addr] = val & 0xFFFFFFFF 
        self.memory_comments[addr] = comment

    def _process_images(self, items):
        for item in items:
            name = item["name"]
            args = item["value"]["args"]
            h0, v0 = int(args[0]['val']), int(args[1]['val'])
            self.images[name] = {"id": self.image_cursor, "h0": h0, "v0": v0}
            self.image_cursor += 1

    def _process_ints(self, items):
        for item in items:
            name = item["name"]
            val = int(item["value"])
            addr = ADDR_INTS_START + self.var_cursor
            if addr >= ADDR_SYS_CONSTS:
                raise Exception("Too many integers defined! Overwriting System Constants.")
            self.vars[name] = addr
            self._write_mem(addr, val, f"int {name}")
            self.var_cursor += 1

    def _collect_control(self, items):
        """Stores control mappings to be injected as instructions later."""
        for item in items:
            btn = item["name"]
            lbl_name = item["value"]["name"]
            # Convert button to byte code (0xFF for physical button 'button')
            if btn == "button":
                code = 0xFF
            elif len(btn) == 1:
                code = ord(btn)
            else:
                code = 0
            
            self.control_map.append({"code": code, "label": lbl_name, "btn_name": btn})

    def _process_shapes(self, items, is_static):
        count = 0
        group_name = "Static" if is_static else "Dynamic"
        for item in items:
            name = item["name"]
            sid = self.shape_cursor
            self.shapes[name] = sid
            
            constructor = item["value"]
            cls = constructor["class"]
            args = constructor["args"]
            
            h0, v0, h1, v1 = 0,0,0,0
            mode, anchor = 0, 0
            enable = 1 
            color, img_ptr = 0, 0
            type_flag = 0 if cls == "Rect" else 1

            pos_args = [a['val'] for a in args if a['mode'] == 'positional']
            if len(pos_args) >= 4: h0, v0, h1, v1 = pos_args[0:4]

            named_args = {a['key']: a['val'] for a in args if a['mode'] == 'named'}
            
            # Parsing Attributes
            if "img" in named_args:
                img_name = named_args["img"]["name"]
                if img_name in self.images:
                    img_ptr = self.images[img_name]["id"]
                    mode = 1 # Image Mode
            elif "color" in named_args:
                c = named_args["color"]
                # Assuming list [r, g, b] variables or numbers
                # Since prompt implies direct assignment, we take simplified approach:
                # If they are numbers, pack them. If vars, we can't pre-calculate in static memory easily
                # without LDI/ST. Assuming Literals for static definition for now.
                try: 
                    color = (int(c[0])<<16)|(int(c[1])<<8)|int(c[2])
                except: 
                    pass # Handle vars later if needed

            if "flags" in named_args:
                for f in named_args["flags"]:
                    fname = f['name'] if isinstance(f, dict) else str(f)
                    if fname == 'transparent': mode = 2

            if "anchor" in named_args:
                an = named_args["anchor"]["name"]
                mapping = {"top_left":0, "top_right":1, "bot_left":2, "bot_right":3}
                anchor = mapping.get(an, 0)

            # Construct Flag Word
            # Bit 31: Type, 30-29: Anchor, 28-27: Mode, 26: Enable, 23-0: Payload
            payload = img_ptr if mode == 1 else color
            flag_word = (type_flag << 31) | (anchor << 29) | (mode << 27) | (enable << 26) | (payload & 0xFFFFFF)

            self._write_mem(ADDR_SHAPE_FLAG + sid, flag_word, f"{group_name} {name} FLAGS")
            self._write_mem(ADDR_SHAPE_H0 + sid, self._resolve_val(h0), f"{name}.h0")
            self._write_mem(ADDR_SHAPE_V0 + sid, self._resolve_val(v0), f"{name}.v0")
            self._write_mem(ADDR_SHAPE_H1 + sid, self._resolve_val(h1), f"{name}.h1")
            self._write_mem(ADDR_SHAPE_V1 + sid, self._resolve_val(v1), f"{name}.v1")

            self.shape_cursor += 1
            count += 1
        return count

    def _resolve_val(self, val):
        return val if isinstance(val, int) else 0

    # -------------------------------------------------------------------------
    # CODE GEN
    # -------------------------------------------------------------------------
    def _inject_bootstrap(self):
        """Generates instructions to set up the controller before user code runs."""
        
        # 1. Register Interrupts (NEW_INTER)
        # Format: CALL (Type=5), Char (23-16), Addr (15-0)
        for ctrl in self.control_map:
            char_code = ctrl["code"]
            label_name = ctrl["label"]
            addr = self.labels.get(label_name, 0) # 0 in Pass 1
            
            payload = (char_code << 16) | (addr & 0xFFFF)
            opcode  = (OP_CALL << 28) | (FUNC_NEW_INTER << 24) | payload
            
            self._emit(opcode, f"NEW_INTER '{ctrl['btn_name']}' -> {label_name}(@{addr:03X})")

        # 2. Load Images (IMG)
        for name, img in self.images.items():
            h0, v0, ptr = img['h0'], img['v0'], img['id']
            # IMG Payload: h0(23-14), v0(13-5), ptr(4-0)
            payload = ((h0 & 0x3FF) << 14) | ((v0 & 0x1FF) << 5) | (ptr & 0x1F)
            self._emit((OP_CALL << 28) | (FUNC_IMG << 24) | payload, 
                       f"CALL IMG '{name}'")
                       
        # 3. Initial Static Render
        self._emit((OP_CALL << 28) | (FUNC_RENDER_STATIC << 24), "CALL RENDER_STATIC")

    def _generate_code(self, pass_number):
        for stmt in self.ast.get("program_body", []):
            self._compile_stmt(stmt, pass_number)

    def _compile_stmt(self, stmt, pass_number):
        stype = stmt["type"]

        if stype == "LABEL":
            if pass_number == 1: 
                self.labels[stmt["name"]] = self.pc
            if pass_number == 2:
                self.program_data.append((self.pc, 0, f"--- LABEL {stmt['name']} ---"))
                self.program_data.pop() # Remove dummy, just keep index clean

        elif stype == "CALL":
            op = stmt["opcode"]
            if op == "WAIT":
                arg = stmt["arg"]
                self._emit((OP_CALL<<28)|(FUNC_WAIT<<24)|(arg&0xFF), f"CALL WAIT '{chr(arg) if arg!=255 else 'BTN'}'")
            elif op == "IMG":
                # User usually doesn't call IMG manually, but if they do:
                # Implementation depends on args structure
                pass 
            else:
                f_code = {"RENDER": FUNC_RENDER, "HALT": FUNC_HALT, "RENDER_STATIC": FUNC_RENDER_STATIC}.get(op, 0)
                self._emit((OP_CALL<<28)|(f_code<<24), f"CALL {op}")

        elif stype == "ASSIGN":
            addr = self.vars[stmt["target"]]
            self._compile_expr(stmt["expr"], 0)
            self._emit((OP_ST<<28)|(0<<24)|(addr&0xFFFF), f"ST R0 -> {stmt['target']}")

        elif stype == "PROP_ASSIGN":
            prop = stmt["prop_name"]
            sid = self.shapes[stmt["obj_name"]]
            
            # --- Enable Flag Handling ---
            if prop == "enable":
                flag_addr = ADDR_SHAPE_FLAG + sid
                self._compile_expr(stmt["expr"], 0)
                
                # Check if literal 0 or 1
                val = -1
                if isinstance(stmt["expr"], int): val = stmt["expr"]
                elif isinstance(stmt["expr"], dict) and stmt["expr"].get("type") == "val_num": val = stmt["expr"]["value"]
                
                if val == 1:
                    self._emit((OP_LD<<28)|(1<<24)|(flag_addr&0xFFFF), "LD R1, FLAGS")
                    self._emit((OP_LD<<28)|(2<<24)|(ADDR_SYS_CONSTS&0xFFFF), "LD R2, SYS_BIT_26")
                    self._emit((OP_OR<<28)|(1<<24)|(2<<20), "OR R1, R2")
                    self._emit((OP_ST<<28)|(1<<24)|(flag_addr&0xFFFF), "ST R1, FLAGS")
                elif val == 0:
                    self._emit((OP_LD<<28)|(1<<24)|(flag_addr&0xFFFF), "LD R1, FLAGS")
                    self._emit((OP_LD<<28)|(2<<24)|((ADDR_SYS_CONSTS+1)&0xFFFF), "LD R2, SYS_MASK_INV")
                    self._emit((OP_AND<<28)|(1<<24)|(2<<20), "AND R1, R2")
                    self._emit((OP_ST<<28)|(1<<24)|(flag_addr&0xFFFF), "ST R1, FLAGS")
            else:
                base = {"h0":ADDR_SHAPE_H0, "v0":ADDR_SHAPE_V0, "h1":ADDR_SHAPE_H1, "v1":ADDR_SHAPE_V1}[prop]
                self._compile_expr(stmt["expr"], 0)
                self._emit((OP_ST<<28)|(0<<24)|((base+sid)&0xFFFF), f"ST R0 -> {stmt['obj_name']}.{prop}")

        elif stype == "WHILE":
            start, branch_idx = self.pc, self.pc
            self._compile_cond(stmt["condition"])
            self._emit(0, "BRANCH PLACEHOLDER")
            for s in stmt["body"]:
                if s["type"] == "BREAK": self._emit_jump_placeholder(is_break=True)
                else: self._compile_stmt(s, pass_number)
            self._emit((OP_JMP<<28)|(start&0xFFFF), f"JMP @{start:03X} (Loop)")
            end = self.pc
            self._patch_branch(branch_idx, stmt["condition"]["op"], end, invert=True)
            self._patch_breaks(start, end)

        elif stype == "IF":
            self._compile_cond(stmt["condition"])
            branch_idx = self.pc
            self._emit(0, "BRANCH PLACEHOLDER")
            for s in stmt["body_true"]: self._compile_stmt(s, pass_number)
            jump_idx = self.pc
            self._emit(0, "JUMP PLACEHOLDER")
            else_pc = self.pc
            self._patch_branch(branch_idx, stmt["condition"]["op"], else_pc, invert=True)
            if "body_false" in stmt:
                for s in stmt["body_false"]: self._compile_stmt(s, pass_number)
            end = self.pc
            self._patch_jump(jump_idx, end)

    def _compile_expr(self, expr, reg):
        chain = expr["op_chain"] if isinstance(expr, dict) and "op_chain" in expr else [expr]
        self._load_term(chain[0], reg)
        i = 1
        while i < len(chain):
            op, term = chain[i], chain[i+1]
            self._load_term(term, 1) 
            opcode = { "+": OP_ADD, "-": OP_SUB, "&": OP_AND, "|": OP_OR }[op]
            self._emit((opcode<<28)|(reg<<24)|(1<<20), f"{op} R{reg}, R1")
            i += 2

    def _load_term(self, term, reg):
        if isinstance(term, int):
            self._emit((OP_LDI<<28)|(reg<<24)|(term&0xFFFFFF), f"LDI R{reg}, {term}")
        elif isinstance(term, dict):
            addr = self.vars[term["name"]]
            self._emit((OP_LD<<28)|(reg<<24)|(addr&0xFFFF), f"LD R{reg}, {term['name']}")

    def _compile_cond(self, cond):
        self._compile_expr(cond["left"], 0)
        self._compile_expr(cond["right"], 1)
        self._emit((OP_CMP<<28)|(0<<24)|(1<<20), "CMP R0, R1")

    def _emit(self, instr, asm=""):
        self.program_data.append((self.pc, instr, asm))
        self.pc += 1

    def _emit_jump_placeholder(self, is_break=False):
        self.program_data.append((self.pc, "BREAK" if is_break else 0, "JMP (Break)"))
        self.pc += 1

    def _patch_branch(self, idx, op, target, invert):
        code, mnem = OP_BEQ, "BEQ"
        if invert:
             if op == ">": code, mnem = OP_BLT, "BLT" 
             elif op == "<": code, mnem = OP_BGT, "BGT"
             else: code, mnem = OP_BEQ, "BEQ (Inv)"
        else:
             if op == ">": code, mnem = OP_BGT, "BGT"
             elif op == "<": code, mnem = OP_BLT, "BLT"

        instr = (code << 28) | (target & 0xFFFF)
        old_addr, _, _ = self.program_data[idx]
        self.program_data[idx] = (old_addr, instr, f"{mnem} @{target:03X}")

    def _patch_jump(self, idx, target):
        instr = (OP_JMP << 28) | (target & 0xFFFF)
        old_addr, _, _ = self.program_data[idx]
        self.program_data[idx] = (old_addr, instr, f"JMP @{target:03X}")

    def _patch_breaks(self, start, end):
        for i in range(len(self.program_data)):
            addr, instr, asm = self.program_data[i]
            if instr == "BREAK" and addr >= start:
                new_instr = (OP_JMP << 28) | (end & 0xFFFF)
                self.program_data[i] = (addr, new_instr, f"JMP @{end:03X} (Break)")

    # -------------------------------------------------------------------------
    # OUTPUT GENERATORS
    # -------------------------------------------------------------------------
    def get_hex_mem(self):
        lines = []
        full_map = self.memory_init.copy()
        for addr, instr, _ in self.program_data:
            val = instr if isinstance(instr, int) else 0
            full_map[addr] = val
        for addr in sorted(full_map.keys()):
            lines.append(f"@{addr:03X} {full_map[addr]:08X}")
        return "\n".join(lines)

    def get_assembly(self):
        lines = []
        lines.append("; --- DATA SECTION ---")
        for addr in sorted(self.memory_init.keys()):
            val = self.memory_init[addr]
            cmt = self.memory_comments.get(addr, "")
            lines.append(f"@{addr:03X} : {val:08X}  ; {cmt}")
            
        lines.append("\n; --- CODE SECTION ---")
        for addr, instr, asm in self.program_data:
            hex_str = f"{instr:08X}" if isinstance(instr, int) else "????????"
            lines.append(f"@{addr:03X} : {hex_str}  ; {asm}")
        return "\n".join(lines)

    def get_uart_binary(self):
        # Determine size (Must be enough to cover Program + Data)
        # Highest address is likely in V1 array (around 737)
        max_addr = ADDR_SHAPE_V1 + 32
        
        # Buffer (size in bytes = words * 4)
        buffer_size = (max_addr + 1) * 4
        raw_data = bytearray(buffer_size)

        def write_word(addr, val):
            struct.pack_into('>I', raw_data, addr * 4, val & 0xFFFFFFFF)

        # 1. Fill Program
        for addr, instr, _ in self.program_data:
            write_word(addr, instr if isinstance(instr, int) else 0)

        # 2. Fill Data
        for addr, val in self.memory_init.items():
            write_word(addr, val)

        # 3. Append EOF
        eof_bytes = struct.pack('>I', EOF_MARKER)
        return raw_data + eof_bytes

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="AST JSON file")
    parser.add_argument("asm", help="Output Assembly (.asm) file")
    parser.add_argument("mem", help="Output Hex (.mem) file")
    parser.add_argument("bin", help="Output Binary (.bin) file")
    args = parser.parse_args()

    try:
        with open(args.input, "r") as f:
            ast = json.load(f)
            
        compiler = RenderEngineCompiler(ast)
        compiler.compile()
        
        with open(args.asm, "w") as f: f.write(compiler.get_assembly())
        with open(args.mem, "w") as f: f.write(compiler.get_hex_mem())
        with open(args.bin, "wb") as f: f.write(compiler.get_uart_binary())
            
        print(f"Generated:")
        print(f"  - {args.asm}")
        print(f"  - {args.mem}")
        print(f"  - {args.bin} (Big Endian, with EOF)")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
