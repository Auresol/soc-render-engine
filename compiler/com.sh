#!/bin/bash

# Check if an input file was provided
if [ -z "$1" ]; then
    echo "Usage: ./compile.sh <source_file>"
    echo "Example: ./compile.sh test_game.txt"
    exit 1
fi

INPUT_FILE="$1"
# Extract filename without extension (e.g., test_game.txt -> test_game)
BASENAME="${INPUT_FILE%.*}"

AST_FILE="${BASENAME}.json"
ASM_FILE="${BASENAME}.asm"
MEM_FILE="${BASENAME}.mem"
BIN_FILE="${BASENAME}.bin"

echo "========================================"
echo "      FPGA Render Engine Compiler       "
echo "========================================"
echo "Input:  $INPUT_FILE"

# 1. Run AST Transformer
echo -n "[1/2] Generating AST... "
python3 ast_transformer.py "$INPUT_FILE" "$AST_FILE"
if [ $? -ne 0 ]; then
    echo "FAILED"
    echo "Error running ast_transformer.py"
    exit 1
fi
echo "OK ($AST_FILE)"

# 2. Run Compiler
echo -n "[2/2] Generating Machine Code... "
python3 compiler.py "$AST_FILE" "$ASM_FILE" "$MEM_FILE" "$BIN_FILE"
if [ $? -ne 0 ]; then
    echo "FAILED"
    echo "Error running compiler.py"
    exit 1
fi
echo "OK"

echo "========================================"
echo "Build Successful!"
echo "Generated:"
echo "  - $AST_FILE (Debug AST)"
echo "  - $ASM_FILE (Human Readable)"
echo "  - $MEM_FILE (FPGA Binary)"
echo "========================================" 
