# core 套件初始化
# 匯出常用模組，方便直接 import core
from .io_utils import ask_input, ThinkingDots
from .model_interface import build_code_prompt, build_test_prompt, build_explain_prompt, generate_response, call_ollama_cli, build_virtual_code_prompt
from .code_extract import extract_code_block, extract_json_block, parse_tests_from_text, normalize_tests
from .data_structures import ListNode, TreeNode, auto_convert_input, auto_convert_output
from .validators import validate_python_code, validate_main_function, _normalize_output
from .test_utils import generate_tests, generate_and_validate
from .data_loader import load_all_json_from_dir, format_data_for_rag, load_all_problems_from_file

