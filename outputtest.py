import os
import json
import ast
import time
import textwrap
import re  # 導入 re 模組用於建立安全檔案名
from pathlib import Path
from typing import List, Dict, Any

# === 導入核心模組 (確保腳本在 backend/ 目錄下運行) ===
from core.model_interface import generate_structured_tests, normalize_tests
from core.judge_core import validate_leetcode_code, infer_method_name_from_code

# === 模擬 main.py 中的環境設置 ===
PYTHON_PRELUDE = """
import sys, os, math, collections, itertools, functools, heapq, bisect, re, random, copy
from typing import *
from collections import Counter, defaultdict, deque, OrderedDict
from functools import lru_cache, cache, cmp_to_key, reduce
from heapq import heapify, heappush, heappop, heappushpop, heapreplace, nlargest, nsmallest
from itertools import accumulate, permutations, combinations, combinations_with_replacement, product, groupby, cycle, islice, count
from bisect import bisect_left, bisect_right, insort, insort_left, insort_right
from math import gcd, ceil, floor, sqrt, log, log2, log10, pi, inf, factorial, comb, perm
"""

# === 從 main.py 提取的輔助函式 ===
def get_solution_method_info(code: str):
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

def run_experiment(problem: Dict[str, Any]) -> Dict[str, Any]:
    """
    接收單一道題目的資料 (dict)，執行 AI 測資生成 + 驗證。
    
    返回:
        一個包含詳細結果的字典，用於儲存。
    """
    print(f"=== 開始實驗: {problem.get('title', 'Unknown')} ===")
    
    # 統一定義錯誤返回結構
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

    try:
        user_code = problem['solution']
        user_need = problem['description']
    except KeyError as e:
        print(f"[錯誤] 缺少必要欄位: {e}")
        return {**base_error_return, "error": f"缺少欄位: {e}"}

    # 2. 模擬 main.py 模式 2 的測資生成請求
    print("\n[Step 1] 呼叫 AI 生成測資...")
    need_with_code_context = f"需求說明:\n{user_need}\n\n參考程式碼(請確保測資能作為此程式的合法輸入):\n```python\n{user_code}\n```"
    
    json_tests = []
    try:
        raw_tests = generate_structured_tests(need_with_code_context)
        json_tests = normalize_tests(raw_tests)
        if not json_tests: # 確保至少有一筆測資，否則後續 total_tests 為 0 會導致 0/0
             print("[警告] AI 未生成任何有效測資。")
             return {**base_error_return, "error": "AI 未生成任何有效測資", "generated_tests": raw_tests}
        print(f"[AI 回應] 成功提取 {len(json_tests)} 筆測資")
    except Exception as e:
        print(f"[錯誤] AI 測資生成失敗: {e}")
        return {**base_error_return, "error": f"AI 測資生成失敗: {e}"}

    # 3. 模擬 main.py 模式 2 的參數解析與驗證流程
    print("\n[Step 2] 執行參數解析與驗證 (LeetCode 模式)...")
    code_to_run = PYTHON_PRELUDE + "\n" + user_code

    if "class Solution" in user_code:
        method_name, expected_arg_count = get_solution_method_info(user_code)
        if not method_name:
            method_name = infer_method_name_from_code(user_code)
        
        print(f"[分析] 偵測到目標方法: {method_name}, 預期參數數量: {expected_arg_count}")

        core_tests = []
        for i, t in enumerate(json_tests, 1):
            inp = t.get("input")
            out = t.get("output")
            print(f"  - 處理測資 #{i}: 輸入 raw='{inp}'")

            # --- 智慧參數解包邏輯 (從 main.py 複製) ---
            args = None
            if isinstance(inp, list) and expected_arg_count > 1 and len(inp) == expected_arg_count:
                args = tuple(inp)
            elif isinstance(inp, str):
                try:
                    parsed = json.loads(inp)
                    if isinstance(parsed, list) and expected_arg_count > 1 and len(parsed) == expected_arg_count:
                        args = tuple(parsed)
                    elif expected_arg_count == 1:
                        args = (parsed,)
                except:
                    try:
                        try_tuple_str = inp.strip()
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
            
            if args is None:
                print(f"    [警告] 無法智慧解析輸入，回退為原始字串單一參數")
                args = (inp,)

            # --- 預期輸出解析 ---
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

        # 4. 執行驗證
        print("\n[Step 3] 執行 judge_core 驗證...")
        all_passed, runlog = validate_leetcode_code(code_to_run, core_tests, class_name="Solution")
        
        print("\n=== 驗證結果報告 ===")
        print(runlog)
        print(f"\n最終判定: {'✅ 全部通過' if all_passed else '❌ 部分失敗'}")

        # 5. 組合詳細結果
        total_tests = len(core_tests)
        passed_count = 0

        # ⭐️ [修正]：
        # 1. 優先使用 all_passed 布林值。如果全對，passed_count 直接等於 total_tests。
        #    (這解決了 "全對時 acc 為 0" 的問題)
        if all_passed:
            passed_count = total_tests
        else:
        # 2. 如果並非全對 (有部分失敗)，才去解析 runlog 計算部分通過的 '✅' 數量。
            # 逐行計算 runlog，只計算以 "✅" (測資通過) 開頭的行
            for line in runlog.splitlines():
                if line.strip().startswith("✅"):
                    passed_count += 1
        
        # 確保 total_tests 不為 0 (雖然前面已檢查過 json_tests)
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

    else:
        print("[提示] 非 LeetCode 格式程式碼，本實驗腳本僅測試 LeetCode 模式。")
        return {**base_error_return, "error": "非 LeetCode 格式程式碼"}

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
    DATA_DIR = script_dir / "data" / "Leetcode"
    result_dir = script_dir / "results_build_tests"
    result_dir.mkdir(parents=True, exist_ok=True)

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 (多檔版本) ---")
    overall_start_time = time.time()

    for run_index in range(1, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")
        
        # 為每次
        current_run_result_dir = result_dir / f"run_{run_index:02d}"
        current_run_result_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.time()
        json_files = list(DATA_DIR.rglob("*.json"))
        all_results_summary = [] # 用於儲存摘要資訊以生成 summary 檔案
        files_processed = 0
        files_failed_load = 0

        for file_path in json_files:
            if file_path.name in {"leetcode_index.json", "README.md"}:
                continue
            print(f"\n--- 處理檔案: {file_path.relative_to(DATA_DIR)} ---")

            problems = load_all_problems_from_file(file_path)
            if not problems:
                files_failed_load += 1
                continue

            for idx, (title, desc, examples, sol) in enumerate(problems):
                problem_data = {"title": title, "description": desc, "examples": examples, "solution": sol}
                
                # 執行實驗並獲取詳細結果
                experiment_result = run_experiment(problem_data)
                
                # --- 新增：儲存單一題目的詳細 JSON ---
                
                # 建立一個安全的檔案名
                source_file_name = file_path.stem
                problem_title_safe = re.sub(r'[\\/*?:"<>|]', "", title) # 移除不安全的檔案名
                result_filename = f"{source_file_name}_idx_{idx}_{problem_title_safe[:50]}.json"
                save_path = current_run_result_dir / result_filename

                # 準備要儲存的完整資料
                output_data = {
                    "run_index": run_index,
                    "source_file": str(file_path.relative_to(DATA_DIR)),
                    "problem_index_in_file": idx,
                    "problem_data": problem_data,
                    "experiment_result": experiment_result
                }

                # 儲存檔案
                try:
                    with open(save_path, 'w', encoding='utf-8') as f:
                        json.dump(output_data, f, indent=2, ensure_ascii=False)
                    print(f"    -> 已儲存詳細結果至: {save_path.relative_to(script_dir)}")
                except Exception as e:
                    print(f"    [錯誤] 儲存 {save_path} 失敗: {e}")

                # -------------------------------------

                # 儲存摘要資訊，用於最後的
                all_results_summary.append({
                    "source_file": str(file_path.relative_to(DATA_DIR)),
                    "problem_index_in_file": idx,
                    "title": title,
                    "generation_result": experiment_result # 傳遞完整的結果
                })
            files_processed += 1

        # === 儲存摘要結果 (原有的邏輯) ===
        SUMMARY_FILE = result_dir / f"summary_run_{run_index:02d}.json"

        # === 統計與錯誤總結 ===
        success_count = 0
        failed_cases = []
        for item in all_results_summary:
            gen_result = item["generation_result"]
            # "success" 現在代表實驗是否成功執行 (無論測資是否通過)
            if gen_result["success"]:
                success_count += 1
            else:
                failed_cases.append({
                    "title": item["title"],
                    "source_file": item["source_file"],
                    "generation_error": gen_result.get("error"),
                    "runlog": gen_result.get("runlog"), # 保留 runlog 以便除錯
                })

        error_summary = {
            "run_index": run_index,
            "total_files_processed": files_processed,
            "files_failed_load": files_failed_load,
            "total_problems_attempted": len(all_results_summary),
            "experiment_success_count": success_count, # 實驗成功執行
            "experiment_failure_count": len(failed_cases), # 實驗執行失敗 (如 AI 生成失敗)
            "failed_cases_details": failed_cases,
        }

        try:
            with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
                json.dump(error_summary, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[錯誤] 寫入錯誤摘要失敗: {e}")

        end_time = time.time()
        print(f"--- 第 {run_index} 次完成，耗時 {end_time - start_time:.2f} 秒 ---")
        print(f"--- 摘要報告已儲存至: {SUMMARY_FILE.relative_to(script_dir)} ---")
        print(f"--- 詳細結果已儲存於: {current_run_result_dir.relative_to(script_dir)} 資料夾 ---")


    overall_end_time = time.time()
    print(f"\n--- 所有 {TOTAL_RUNS} 次循環已全部完成 ---")
    print(f"總耗時: {overall_end_time - overall_start_time:.2f} 秒")
    print(f"所有結果已儲存於 {result_dir} 資料夾中。")