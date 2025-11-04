import os
import json
import random
import re  # 導入 re 模組
import subprocess
import tempfile
from core.validators import validate_main_function
from core.data_structures import ListNode, TreeNode, list_to_nodes, nodes_to_list, list_to_tree, tree_to_list, auto_convert_input, auto_convert_output

# 嘗試導入 main.py 中使用的錯誤解釋器
try:
    from core.explain_error import explain_code_error
except ImportError:
    # (*** 錯誤修正 2a ***)
    # 修正：備用函式 (fallback) 應該只接受一個參數 'code'
    def explain_code_error(code):
        print(f"[警告] 'explain_error' 模組載入失敗，無法分析錯誤。")
        return "(錯誤分析模組載入失敗)"

# ---
# === (來自 testrun.py) 標準化函式 ===
# ---
def _normalize_output(s: str) -> str:
    """
    (來自 testrun.py 的驗證邏輯)
    輔助函數：將 stdout 和 expected output 字串標準化以便進行比較。
    """
    if not isinstance(s, str):
        # 對 LeetCode 輸出的 list, int, bool 等
        # 轉換為 Python 的標準字串表示法
        if s is None:
            return "null"
        if isinstance(s, bool):
            return str(s).lower()
        s = str(s)

    s = s.strip()

    # 1. 去除最外層的引號 (e.g., "'bab'" -> "bab" 或 "['...']" -> ['...'])
    if len(s) >= 2:
        if s.startswith("'") and s.endswith("'"):
            s = s[1:-1]
        elif s.startswith('"') and s.endswith('"'):
            s = s[1:-1]

    # 2. 標準化所有內部引號為雙引號
    s = s.replace("'", '"')

    # 3. 去除所有內部的空格
    s = s.replace(" ", "")

    return s

# ---
# === (新增) LeetCode 輔助函式 ===
# ---
def get_data_structures_preamble() -> str:
    """
    返回 LeetCode 題目測試可能需要的輔助類別和函式字串。
    """
    # 這些是 core.data_structures 的內容
    return """
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right

def list_to_nodes(lst):
    dummy = ListNode()
    curr = dummy
    for val in lst:
        curr.next = ListNode(val)
        curr = curr.next
    return dummy.next

def nodes_to_list(node):
    result = []
    while node:
        result.append(node.val)
        node = node.next
    return result

def list_to_tree(lst):
    if not lst:
        return None
    nodes = [TreeNode(val) if val is not None else None for val in lst]
    kids = nodes[::-1]
    root = kids.pop()
    for node in nodes:
        if node:
            if kids: node.left = kids.pop()
            if kids: node.right = kids.pop()
    return root

def tree_to_list(root):
    if not root:
        return []
    result, queue = [], [root]
    while queue:
        node = queue.pop(0)
        if node:
            result.append(node.val)
            queue.append(node.left)
            queue.append(node.right)
        else:
            result.append(None)
    while result and result[-1] is None:
        result.pop()
    return result

# auto_convert_output 是關鍵
def auto_convert_output(result):
    if isinstance(result, ListNode):
        return nodes_to_list(result)
    if isinstance(result, TreeNode):
        return tree_to_list(result)
    return result
"""

def parse_leetcode_info(solution_str: str, input_str: str) -> tuple[str | None, list[str], str]:
    """
    解析 LeetCode 格式的 solution 和 input。
    
    返回: (func_name, arg_names, input_definitions)
    如果
    - func_name 是 None: 表示這是一個 __init__ 型的題目 (如 KthLargest)，無法驗證。
    - func_name 是 str: 表示這是一個標準函式呼叫。
    """
    
    # 1. 嘗試解析函式名稱
    match = re.search(r"def (\w+)\(self, ([^\)]+)\)", solution_str)
    
    if not match:
        # 可能是 __init__ 題目 (e.g., KthLargest, MyLinkedList)
        if "def __init__(self" in solution_str:
            return None, [], ""
        # 備用 regex
        match = re.search(r"def (\w+)\(self, ([^\)]+)\) ->", solution_str)
        if not match:
             return None, [], "" # 真的找不到

    func_name = match.group(1)
    
    # 2. 解析參數名稱 (from def)
    args_str = match.group(2)
    arg_names = [arg.split(':')[0].strip() for arg in args_str.split(',')]
    
    # 3. 準備 input_definitions
    try:
        input_definitions = input_str
        
        # 重新從 input_str 獲取 arg_names，這更可靠
        raw_arg_names = re.findall(r"(\w+)\s*=", input_str)
        
        if set(raw_arg_names) == set(arg_names):
             return func_name, arg_names, input_definitions
        else:
             if not raw_arg_names and not arg_names:
                 return None, [], ""
            
             # (*** 錯誤修正 1 ***)
             # (修正 IndentationError：將此區塊正確縮排到 'else' 內部)
             if not raw_arg_names: 
                 return None, [], "" 
             
             return func_name, raw_arg_names, input_definitions

    except Exception as e:
        print(f"[警告] LeetCode input 解析失敗: {e}")
        return None, [], ""
    # (移除了先前在 try...except 外部的 return)

# ---
# === 主函式 ===
# ---

def list_obj_units(obj_root="data"):
    try:
        return sorted([d for d in os.listdir(obj_root) if os.path.isdir(os.path.join(obj_root, d))])
    except FileNotFoundError:
        print(f"[錯誤] 找不到 'data' 資料夾。")
        return []

def load_all_coding_practice(obj_root="data", unit=None):
    practice_list = []
    search_path = os.path.join(obj_root, unit) if unit else obj_root
    
    if not os.path.exists(search_path):
        print(f"[警告] 路徑不存在: {search_path}")
        return []

    for root, dirs, files in os.walk(search_path):
        for file in files:
            if file.endswith(".json"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "coding_practice" in data:
                            for item in data["coding_practice"]:
                                item["source_file"] = path 
                                practice_list.append(item)
                except Exception as e:
                    print(f"[讀取失敗] {path}: {e}")
    return practice_list


def quiz_mode():
    """
    (已修改)
    出題模式主函式。
    採用 testrun.py 的驗證邏輯：
    1. 呼叫 validate_main_function(..., expected_output=None) 取得原始 stdout。
    2. 使用本地的 _normalize_output 函式進行標準化比對。
    3. (新增) 支援 LeetCode 格式的動態測試腳本生成。
    """
    units = list_obj_units()
    if not units:
        print("[提示] 找不到任何單元資料夾 (如 data/lessons 或 data/Leetcode)。")
        return

    print("請選擇單元：")
    for idx, name in enumerate(units, 1):
        print(f"{idx}. {name}")

    sel = input("輸入單元編號: ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(units)):
        print("[提示] 請輸入有效的編號。")
        return

    unit = units[int(sel) - 1]
    print(f"[載入中] 正在從 {unit} 載入題庫...")
    practices = load_all_coding_practice(unit=unit)
    if not practices:
        print("[提示] 此單元沒有練習題。")
        return

    q = random.choice(practices)
    print(f"\n=== 出題模式 ===\n單元: {unit} (來源: {q.get('source_file', 'N/A')})\n標題: {q['title']}\n描述: {q['description']}\n")

    # 取得範例
    examples_data = q.get("examples")
    example_to_run = None

    if isinstance(examples_data, list) and examples_data:
        example_to_run = examples_data[0] # 取 LeetCode 第一個範例
        print("範例 (LeetCode 格式):", example_to_run)
    elif isinstance(examples_data, dict):
        example_to_run = examples_data # 取 Lesson 範例
        print("範例 (Lesson 格式):", example_to_run)
    else:
        print(" (此題無範例)")

    # 使用者輸入程式碼
    print("\n請輸入你的 Python 解答 (若為 LeetCode 題，請包含 class Solution: ...)，多行輸入，結束請輸入單獨一行 'END'。")
    user_lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        user_lines.append(line)
    user_code = "\n".join(user_lines).strip()

    if not user_code:
        print("[提示] 沒有輸入程式碼，取消驗證。")
        return

    # 檢查 solution 是否為 LeetCode 格式 (Class Solution)
    is_leetcode_format = "class Solution" in q.get("solution", "")

    # ---
    # === (修改) 驗證邏輯 (採用 testrun.py 模式) ===
    # ---
    
    if not example_to_run:
        # --- (A) 無範例 ---
        print("\n[提示] 此題無範例，跳過驗證。")

    elif is_leetcode_format:
        # --- (B) LeetCode 格式驗證 ---
        
        test_input_str = str(example_to_run.get("input", ""))
        test_output_str = str(example_to_run.get("output", ""))
        reference_solution = q.get("solution")

        print("\n[範例測資比對 (LeetCode 模式)]")
        print(f"Input (解析為參數): {repr(test_input_str)}")
        print(f"Expected Output (比對回傳值): {repr(test_output_str)}")
        
        # 1. 解析函式資訊
        func_name, arg_names, input_definitions = parse_leetcode_info(reference_solution, test_input_str)
        
        if func_name is None:
            print("\n  結果: [跳過] ❌")
            print("  [提示] 此 LeetCode 題目格式為類別實例化 (如 KthLargest, MyLinkedList)，")
            print("         或無法解析函式簽名，目前驗證器尚不支援此類題目。")
        else:
            # 2. 構建測試腳本 (Harness)
            harness_code = f"""
# --- 輔助類別 (ListNode, TreeNode, etc.) ---
{get_data_structures_preamble()}

# --- 使用者提交的程式碼 ---
{user_code}
# --- 

import sys
import json

def run_test_harness():
    try:
        # --- 定義範例輸入 ---
        {input_definitions}
        
        # --- 實例化並呼叫 ---
        instance = Solution()
        result = instance.{func_name}({', '.join(arg_names)})
        
        # --- 自動轉換輸出 (例如 ListNode -> list) ---
        final_result = auto_convert_output(result)
        
        # --- 打印原始結果 (非 repr) ---
        print(final_result)
        
    except Exception as e:
        print(f"HarnessExecutionError: {{e}}", file=sys.stderr)

# 執行測試
run_test_harness()
"""
            # 3. 執行驗證 (使用 testrun.py 的比對邏輯)
            validation_result = validate_main_function(
                code=harness_code,
                stdin_input=None, # Harness 不接收 stdin
                expected_output=None # 我們手動比對
            )
            exec_success, raw_output_str = validation_result
            
            success = False
            output_msg = raw_output_str

            if exec_success:
                norm_expected = _normalize_output(test_output_str)
                norm_actual = _normalize_output(raw_output_str)
                
                if norm_expected == norm_actual:
                    success = True
                    output_msg = raw_output_str
                else:
                    success = False
                    output_msg = (
                        f"Actual Output:\n{raw_output_str}\n\n"
                        f"[Output Mismatch (Normalized)]\n"
                        f"Expected: {repr(norm_expected)}\n"
                        f"Got:      {repr(norm_actual)}"
                    )
            else:
                success = False
                output_msg = raw_output_str # 包含 HarnessExecutionError

            # 4. 報告結果
            print(f"  詳細資訊/執行結果:\n{output_msg}")
            if success:
                print("  結果: [成功] 使用者程式碼正確 ✅")
            else:
                print("  結果: [錯誤] 程式執行失敗或輸出與期望不符 ❌")
                print("\n[提示] 程式執行失敗，開始分析...\n")
                try:
                    # (*** 錯誤修正 2b ***)
                    # 修正：只傳入 1 個參數
                    analysis_result = explain_code_error(harness_code)
                    print("\n=== 模型分析 ===\n")
                    print(analysis_result)
                except Exception as e:
                    print(f"\n[分析失敗] {e}")

    else:
        # --- (C) stdin/stdout 格式驗證 (Lessons / data/*.json) ---
        test_input_str = str(example_to_run.get("input", ""))
        test_output_str = str(example_to_run.get("output", ""))

        print("\n[範例測資比對 (stdin/stdout 模式)]")
        print(f"Input (傳入 stdin): {repr(test_input_str)}")
        print(f"Expected Output (比對 stdout): {repr(test_output_str)}")

        validation_result = validate_main_function(
            code=user_code,
            stdin_input=test_input_str, 
            expected_output=None # 手動比對
        )
        exec_success, raw_output_str = validation_result
        
        success = False
        output_msg = raw_output_str

        if exec_success:
            norm_expected = _normalize_output(test_output_str)
            norm_actual = _normalize_output(raw_output_str)
            
            if norm_expected == norm_actual:
                success = True
                output_msg = raw_output_str
            else:
                success = False
                output_msg = (
                    f"Actual Output:\n{raw_output_str}\n\n"
                    f"[Output Mismatch (Normalized)]\n"
                    f"Expected: {repr(norm_expected)}\n"
                    f"Got:      {repr(norm_actual)}"
                )
        else:
            success = False
            output_msg = raw_output_str

        print(f"  詳細資訊/執行結果:\n{output_msg}")
        if success:
            print("  結果: [成功] 使用者程式碼正確 ✅")
        else:
            print("  結果: [錯誤] 程式執行失敗或輸出與期望不符 ❌")
            print("\n[提示] 程式執行失敗，開始分析...\n")
            try:
                # (*** 錯誤修正 2c ***)
                # 修正：只傳入 1 個參數
                fallback_result = explain_code_error(user_code)
                print("\n=== 模型分析 ===\n")
                print(fallback_result)
            except Exception as e:
                print(f"\n[分析失敗] {e}")

    # --- (驗證結束) ---

    # 顯示參考解答 (保持不變)
    print("\n=== 參考解答 ===\n")
    print(q.get("solution", "[無解答]"))