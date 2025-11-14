import sys
import os
import json
import time
import re
import textwrap
import ast
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

# === 環境設定：確保能匯入 backend/core ===
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

try:
    # 引用既有的核心模組
    from core.model_interface import ChainOfThoughtTestAgent, normalize_tests
    from core.judge_core import (
        validate_leetcode_code, 
        infer_method_name_from_code,
         # 如果 judge_core 沒有此函式，下面會定義 fallback
        ListNode, TreeNode # 確保執行環境有這些定義
    )
except ImportError as e:
    print(f"[系統錯誤] 匯入失敗: {e}")
    print("請確保腳本位於 backend/ 目錄下，且 core 模組完整。")
    sys.exit(1)

# === 輔助：模擬 main.py 的 Prelude (讓 LeetCode 程式碼能執行) ===
PYTHON_PRELUDE = """
import sys, os, math, collections, itertools, functools, heapq, bisect, re, random, copy
from typing import *
from collections import Counter, defaultdict, deque, OrderedDict
from functools import lru_cache, cache, cmp_to_key, reduce
from heapq import heapify, heappush, heappop, heappushpop, heapreplace, nlargest, nsmallest
from itertools import accumulate, permutations, combinations, combinations_with_replacement, product, groupby, cycle, islice, count
from bisect import bisect_left, bisect_right, insort, insort_left, insort_right
from math import gcd, ceil, floor, sqrt, log, log2, log10, pi, inf, factorial, comb, perm

# 定義基本資料結構以防使用者程式碼依賴
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right
"""

# 若 judge_core 沒匯出 get_solution_method_info，這裡提供一個本地版本
def local_get_solution_method_info(code: str) -> Tuple[Optional[str], int]:
    try:
        tree = ast.parse(textwrap.dedent(code))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == 'Solution':
                for subnode in node.body:
                    if isinstance(subnode, ast.FunctionDef) and not subnode.name.startswith('_'):
                        arg_count = len(subnode.args.args)
                        if arg_count > 0 and subnode.args.args[0].arg == 'self':
                            arg_count -= 1
                        return subnode.name, max(0, arg_count)
    except Exception:
        pass
    return None, 0

# 嘗試使用匯入的，若無則使用本地的
get_solution_method_info = globals().get('get_solution_method_info', local_get_solution_method_info)


def run_experiment(problem_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    核心實驗邏輯：
    1. 接收題目資料 (標題, 描述, 解答)
    2. 呼叫 Agent 生成測資
    3. 嘗試執行解答並驗證測資是否通過
    4. 回傳統計數據
    """
    title = problem_data.get("title", "Unknown")
    description = problem_data.get("description", "")
    solution_code = problem_data.get("solution", "")
    
    base_error_return = {
        "success": False,
        "error": "",
        "generated_tests": [],
        "parsed_tests": [],
        "runlog": "",
        "all_passed": False,
        "total_tests": 0,
        "passed_count": 0,
        "accuracy_rate": 0.0
    }

    if not solution_code:
        return {**base_error_return, "error": "無參考解答 (Solution code missing)"}

    # 模擬 main.py Mode 2 的 Prompt Context
    # 我們把「參考解答」當作「使用者寫的 code」來讓 Agent 生成測資
    user_need_context = (
        f"需求說明:\n{description}\n\n"
        f"參考程式碼(請確保測資能作為此程式的合法輸入):\n```python\n{solution_code}\n```"
    )

    # 準備執行用的程式碼 (加上 Prelude)
    code_to_run = PYTHON_PRELUDE + "\n" + solution_code

    try:
        # === 步驟 1: 呼叫 Agent 生成測資 ===
        # 這裡使用 ChainOfThoughtTestAgent 流程
        agent = ChainOfThoughtTestAgent() 
        
        # 呼叫 pipeline 取得分析與原始測資 (raw dict list)
        # 注意：這裡我們不傳入 callback 讓它自動執行，因為我們要手動控制執行流程以收集數據
        pipeline_result = agent.run_pipeline(user_need=user_need_context)
        raw_tests = pipeline_result.get("test_cases", [])
        
        # 正規化測資格式 (確保有 input/output 欄位)
        json_tests = normalize_tests(raw_tests)

        if not json_tests:
            return {**base_error_return, "error": "Agent 未能生成有效測資 (normalize_tests returned empty)"}

    except Exception as e:
        return {**base_error_return, "error": f"Agent 生成階段發生例外: {str(e)}"}

    # === 步驟 2: 準備執行驗證 (LeetCode 模式) ===
    if "class Solution" in solution_code:
        try:
            # 分析方法名與參數個數
            method_name, expected_arg_count = get_solution_method_info(solution_code)
            if not method_name:
                method_name = infer_method_name_from_code(solution_code)
            
            if not method_name:
                return {**base_error_return, "error": "無法從解答中解析出方法名稱 (Method name parsing failed)"}

            # 建構核心測資 (Tuple 格式)
            core_tests = []
            for t in json_tests:
                inp = t.get("input")
                out = t.get("output")
                
                # --- 智慧參數解包邏輯 (與 main.py 保持一致) ---
                args = None
                
                # 情況 A: 輸入已是列表，且長度與預期參數個數相同 (>1)
                if isinstance(inp, list) and expected_arg_count > 1 and len(inp) == expected_arg_count:
                    args = tuple(inp)
                
                # 情況 B: 輸入是字串，嘗試解析
                elif isinstance(inp, str):
                    try:
                        # 嘗試 JSON 解析
                        parsed = json.loads(inp)
                        if isinstance(parsed, list) and expected_arg_count > 1 and len(parsed) == expected_arg_count:
                            args = tuple(parsed)
                        elif expected_arg_count == 1:
                            args = (parsed,)
                    except:
                        # 嘗試 AST Literal 解析
                        try:
                            try_tuple_str = inp.strip()
                            # 處理括號
                            if '\n' in try_tuple_str and not (try_tuple_str.startswith('[') and try_tuple_str.endswith(']')):
                                    try_tuple_str = f"({try_tuple_str.replace(chr(10), ',')})"
                            elif not (try_tuple_str.startswith('(') and try_tuple_str.endswith(')')):
                                    try_tuple_str = f"({try_tuple_str})"
                            
                            parsed = ast.literal_eval(try_tuple_str)
                            if isinstance(parsed, tuple) and len(parsed) == expected_arg_count:
                                args = parsed
                            elif expected_arg_count == 1:
                                args = (parsed,) if not isinstance(parsed, tuple) else (parsed,)
                            
                            if args is None:
                                parsed = ast.literal_eval(inp)
                                if isinstance(parsed, (list, tuple)) and expected_arg_count > 1 and len(parsed) == expected_arg_count:
                                    args = tuple(parsed)
                                elif expected_arg_count == 1:
                                    args = (parsed,)
                        except:
                            pass 

                # 預設回退
                if args is None:
                    args = (inp,)

                # 預期輸出解析
                expected_val = out
                if isinstance(out, str):
                    try:
                        expected_val = json.loads(out)
                    except:
                        try:
                            expected_val = ast.literal_eval(out)
                        except:
                            pass

                core_tests.append((method_name, args, expected_val))

            # === 步驟 3: 執行驗證 ===
            all_passed, runlog = validate_leetcode_code(code_to_run, core_tests, class_name="Solution")
            
            # 計算統計數據
            total_tests = len(core_tests)
            # 簡單解析 runlog 來計算通過數量 (因為 validate_leetcode_code 只回傳 bool 和 log)
            passed_count = runlog.count("✅ 通過")
            accuracy_rate = (passed_count / total_tests) if total_tests > 0 else 0.0

            return {
                "success": True, 
                "error": None,
                "generated_tests": json_tests,      # AI 原始生成的測資
                "parsed_tests": [str(t) for t in core_tests], # 實際傳給 judge 的測資 (轉為 str)
                "runlog": runlog,                   # 驗證日誌
                "all_passed": all_passed,           # 是否全部通過
                "total_tests": total_tests,         # 測資總數
                "passed_count": passed_count,       # 通過數量
                "accuracy_rate": accuracy_rate      # 準確率
            }

        except Exception as e:
            return {**base_error_return, "error": f"驗證執行階段發生例外: {str(e)}"}

    else:
        print(f"[提示] 題目 '{title}' 非 LeetCode 格式 (無 class Solution)，跳過測試。")
        return {**base_error_return, "error": "非 LeetCode 格式程式碼 (Skip non-class Solution)"}

def load_all_problems_from_file(file_path: Path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and "coding_practice" in data:
            problems = []
            for p in data["coding_practice"]:
                problems.append((
                    p.get("title", "Untitled"),
                    p.get("description", ""),
                    p.get("examples", []),
                    p.get("solution", "")
                ))
            return problems
    except Exception as e:
        print(f"[錯誤] 載入 {file_path} 失敗: {e}")
    return []

if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    
    # 自動指向 frontend/data/Leetcode
    # 假設腳本在 backend/ 下，資料在 ../frontend/data/Leetcode
    DATA_DIR =  script_dir / "data" / "Leetcode"
    
    result_dir = script_dir / "results_build_tests"
    result_dir.mkdir(parents=True, exist_ok=True)

    if not DATA_DIR.exists():
        print(f"[錯誤] 找不到資料目錄: {DATA_DIR}")
        sys.exit(1)

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 (多檔版本) ---")
    print(f"--- 資料來源: {DATA_DIR} ---")
    overall_start_time = time.time()

    for run_index in range(1, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")
        
        # 為每次循環建立資料夾
        current_run_result_dir = result_dir / f"run_{run_index:02d}"
        current_run_result_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        json_files = list(DATA_DIR.rglob("*.json"))
        all_results_summary = [] 
        files_processed = 0
        files_failed_load = 0

        for file_path in json_files:
            if file_path.name in {"leetcode_index.json", "README.md"}:
                continue
            
            # 為了避免 Log 太多，只印出處理的檔名
            # print(f"--- 處理檔案: {file_path.name} ---")

            problems = load_all_problems_from_file(file_path)
            if not problems:
                files_failed_load += 1
                continue

            for idx, (title, desc, examples, sol) in enumerate(problems):
                problem_data = {"title": title, "description": desc, "examples": examples, "solution": sol}
                
                # 執行實驗
                experiment_result = run_experiment(problem_data)
                
                # 儲存單一題目的詳細結果
                source_file_name = file_path.stem
                problem_title_safe = re.sub(r'[\\/*?:"<>|]', "", title)
                # 檔名加上 run_index 防止覆蓋 (雖然已經分資料夾了)
                result_filename = f"{source_file_name}_p{idx}_{problem_title_safe[:30]}.json"
                save_path = current_run_result_dir / result_filename

                output_data = {
                    "run_index": run_index,
                    "source_file": str(file_path),
                    "problem_index_in_file": idx,
                    "problem_data": {k:v for k,v in problem_data.items() if k != 'solution'}, # 節省空間不存 solution
                    "experiment_result": experiment_result
                }

                try:
                    with open(save_path, 'w', encoding='utf-8') as f:
                        json.dump(output_data, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"    [錯誤] 儲存 {save_path.name} 失敗: {e}")

                # 收集摘要
                all_results_summary.append({
                    "source_file": file_path.name,
                    "problem_index": idx,
                    "title": title,
                    "success": experiment_result["success"],
                    "all_passed": experiment_result["all_passed"],
                    "accuracy": experiment_result["accuracy_rate"],
                    "error": experiment_result["error"]
                })
                
                # 顯示進度條點點
                print(".", end="", flush=True)

            files_processed += 1
        
        print() # 換行

        # === 儲存該次循環的總摘要 ===
        SUMMARY_FILE = result_dir / f"summary_run_{run_index:02d}.json"

        # 統計數據
        success_exec_count = sum(1 for r in all_results_summary if r["success"])
        all_passed_count = sum(1 for r in all_results_summary if r.get("all_passed"))
        failed_cases = [r for r in all_results_summary if not r["success"]]

        summary_data = {
            "run_index": run_index,
            "total_files": files_processed,
            "total_problems": len(all_results_summary),
            "execution_success": success_exec_count,
            "perfect_pass_count": all_passed_count,
            "failed_details": failed_cases,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
                json.dump(summary_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[錯誤] 寫入摘要失敗: {e}")

        end_time = time.time()
        print(f"\n--- 第 {run_index} 次循環完成 ---")
        print(f"    耗時: {end_time - start_time:.2f} 秒")
        print(f"    執行成功題目數: {success_exec_count}/{len(all_results_summary)}")
        print(f"    測資全過題目數: {all_passed_count}/{len(all_results_summary)}")
        print(f"    摘要報告: {SUMMARY_FILE.name}")

    overall_end_time = time.time()
    print(f"\n{'='*40}")
    print(f"所有 {TOTAL_RUNS} 次循環已全部完成")
    print(f"總耗時: {overall_end_time - overall_start_time:.2f} 秒")
    print(f"結果位置: {result_dir}")