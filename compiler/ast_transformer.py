import sys
import json
import argparse
from lark import Lark, Transformer, Token

# ==========================================
# 1. The Grammar
# ==========================================
grammar = r"""
    start: block* statement*

    // --- Declarations ---
    block: NAME "{" assignment* "}"
    assignment: NAME "=" value

    value: NUMBER                  -> val_num
         | NAME                    -> val_var
         | SQ_STRING               -> val_char 
         | constructor             -> val_constr // FIX: Added alias to prevent JSON error
         | "[" list_items "]"      -> val_list

    constructor: NAME "(" args ")"
    args: arg ("," arg)*
    arg: expression                -> arg_pos
       | NAME "=" expression       -> arg_named

    list_items: expression ("," expression)*

    // --- Logic & Control Flow ---
    code_block: "{" statement* "}"

    statement: "label" NAME                             -> label_stmt
             | "while" "(" condition ")" code_block     -> while_stmt
             | "break"                                  -> break_stmt
             | "if" "(" condition ")" code_block ("else" code_block)? -> if_stmt
             | NAME "." NAME "=" expression             -> prop_set
             | NAME "=" expression                      -> var_set
             | NAME "(" [args] ")"                      -> call_stmt

    // --- Expressions ---
    condition: expression GEN_CMP expression -> binary_op
    
    expression: term (GEN_OP term)*
    term: value 
        | "(" expression ")"       -> term_paren

    GEN_CMP: ">" | "<" | "==" | "!=" | ">=" | "<="
    GEN_OP: "+" | "-" | "&" | "|"
    
    SQ_STRING: "'" /[^']+/ "'" 
    
    %import common.CNAME -> NAME
    %import common.INT -> NUMBER
    %import common.WS
    %import common.CPP_COMMENT
    %ignore WS
    %ignore CPP_COMMENT
"""

# ==========================================
# 2. The Transformer
# ==========================================
class RenderEngineTransformer(Transformer):
    def start(self, items):
        blocks = {}
        statements = []
        for item in items:
            if isinstance(item, dict) and "block_type" in item:
                b_type = item["block_type"]
                if b_type not in blocks:
                    blocks[b_type] = []
                blocks[b_type].extend(item["content"])
            else:
                statements.append(item)
        
        return {
            "program_header": blocks,
            "program_body": statements
        }

    # --- Block Handling ---
    def block(self, items):
        return {"block_type": str(items[0]), "content": items[1:]}

    def assignment(self, items):
        return {"name": str(items[0]), "value": items[1]}

    # --- Value Processing ---
    def val_num(self, n):
        return int(n[0])

    def val_var(self, s):
        return {"type": "var", "name": str(s[0])}

    def val_char(self, s):
        content = str(s[0])[1:-1]
        if content == '*':
            return 0xFF
        return ord(content[0])

    def val_constr(self, items):
        # Unwrap the constructor result
        return items[0]

    def val_list(self, items):
        # items[0] is the list from list_items
        return items[0]

    def list_items(self, items):
        # Filter out commas
        return [item for item in items if not isinstance(item, Token)]

    def constructor(self, items):
        return {
            "type": "obj_init",
            "class": str(items[0]),
            "args": items[1]
        }

    # --- Arguments ---
    def args(self, items):
        # Filter commas
        return [item for item in items if not isinstance(item, Token)]

    def arg_pos(self, items):
        return {"mode": "positional", "val": items[0]}

    def arg_named(self, items):
        return {"mode": "named", "key": str(items[0]), "val": items[1]}

    # --- Logic Statements ---
    def label_stmt(self, items):
        return {"type": "LABEL", "name": str(items[0])}

    def var_set(self, items):
        return {
            "type": "ASSIGN",
            "target": str(items[0]),
            "expr": items[1]
        }

    def prop_set(self, items):
        return {
            "type": "PROP_ASSIGN",
            "obj_name": str(items[0]),
            "prop_name": str(items[1]),
            "expr": items[2]
        }

    def break_stmt(self, items):
        return {"type": "BREAK"}

    def call_stmt(self, items):
        func_name = str(items[0])
        func_args = items[1] if len(items) > 1 and items[1] is not None else []
        
        if func_name == "wait_for_button":
            # Extract val from arg_pos dict
            arg_val = func_args[0]['val'] 
            return {
                "type": "CALL",
                "opcode": "WAIT",
                "arg": arg_val
            }
        elif func_name == "render":
             return {"type": "CALL", "opcode": "RENDER"}
        elif func_name == "render_static":
             return {"type": "CALL", "opcode": "RENDER_STATIC"}
        elif func_name == "halt":
             return {"type": "CALL", "opcode": "HALT"}
        elif func_name == "img":
             return {"type": "CALL", "opcode": "IMG", "arg": func_args}

        return {"type": "CALL_UNKNOWN", "name": func_name, "args": func_args}

    def while_stmt(self, items):
        return {
            "type": "WHILE",
            "condition": items[0],
            "body": items[1]
        }

    def if_stmt(self, items):
        stmt = {
            "type": "IF",
            "condition": items[0],
            "body_true": items[1]
        }
        if len(items) > 2:
            stmt["body_false"] = items[2]
        return stmt

    def code_block(self, items):
        return [item for item in items if not isinstance(item, Token)]

    # --- Expressions ---
    def binary_op(self, items):
        return {
            "left": items[0],
            "op": str(items[1]), 
            "right": items[2]
        }

    def expression(self, items):
        if len(items) == 1:
            return items[0]
        
        clean_chain = []
        for i in items:
            if isinstance(i, Token):
                clean_chain.append(str(i))
            else:
                clean_chain.append(i)
        return {"op_chain": clean_chain}

    def term(self, items):
        return items[0]
        
    def term_paren(self, items):
        return items[1]

# ==========================================
# 3. Main Execution
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AST Transformer for FPGA Render Engine")
    parser.add_argument("input", help="Input source file path")
    parser.add_argument("output", help="Output JSON file path")

    args = parser.parse_args()

    try:
        with open(args.input, "r") as f:
            source_code = f.read()

        lark_parser = Lark(grammar, start='start', parser='lalr')
        tree = lark_parser.parse(source_code)
        
        ast = RenderEngineTransformer().transform(tree)
        
        with open(args.output, "w") as f:
            json.dump(ast, f, indent=2)
            
        print(f"Successfully compiled AST to {args.output}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
