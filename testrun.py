import json
import os
import sys
import pathlib
import time
from typing import Optional, List, Dict, Any, Tuple
import traceback

# --- 解決 ImportError 的路徑修正 ---
script_dir = pathlib.Path(__file__).parent.resolve()
core_dir = script_dir / "core"
if not core_dir.is_dir():
    print(f"[錯誤] 'core' 資料夾未找到於: {core_dir}")
    exit(1)
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))
# --- 路徑修正結束 ---


# --- 導入 Core 模組 (遵守使用者限制) ---
try:
    # (修改) 導入 main.py (模式 1) 所需的函式
    from core import (
        generate_response, 
        extract_code_block, 
        extract_json_block,  # <-- 新增 (main.py 邏輯)
        validate_main_function,
        _normalize_output      # <-- 新增 (從 core 導入)
    )
    from core.model_interface import (
        build_virtual_code_prompt,
        build_test_prompt,     # <-- 新增 (main.py 邏輯)
        build_stdin_code_prompt,
        call_ollama_cli  # <-- 新增 (main.py 邏輯)
    )

except ImportError as e:
    print(f"[嚴重錯誤] 導入 'core' 模組時發生錯誤: {e}")
    print("請確保 core/__init__.py, core/model_interface.py, core/code_extract.py, core/validators.py 均存在。")
    exit(1)
# --- 導入結束 ---


# --- (移除 testrun.py 本地的 _normalize_output 定義) ---


def load_all_problems_from_file(file_path: pathlib.Path) -> List[Tuple[str, str, List[Dict[str, str]], Optional[str]]]:
    """
    (*** 重大修改 ***)
    (此函式保持不變)
    """
    all_problems = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        default_title = file_path.stem
        problems_list = []

        # 1. 嘗試 'coding_practice' 結構 (這現在是一個列表)
        if "coding_practice" in data and isinstance(data["coding_practice"], list):
            problems_list = data["coding_practice"]
        
        # 2. 備用：如果頂層就是一個有效的題目結構（雖然不常見）
        elif "description" in data or "solution" in data:
             # 將整個頂層 data 視為單一問題
             problems_list = [data]

        if not problems_list:
            print(f"  [警告] 在 {file_path.name} 中找不到 'coding_practice' 列表或有效的頂層題目。")
            return []

        # --- 迭代檔案中的 *所有* 題目 ---
        for index, problem in enumerate(problems_list):
            if not isinstance(problem, dict):
                print(f"  [警告] {file_path.name} 中索引 {index} 處的項目不是一個有效的物件（字典）。")
                continue

            title = problem.get("title", f"{default_title}_problem_{index+1}")
            description = problem.get("description", problem.get("content"))
            solution = problem.get("solution")
            raw_examples = problem.get("examples")
            examples = []

            # 格式化 examples
            if isinstance(raw_examples, list):
                examples = raw_examples
            elif isinstance(raw_examples, dict):
                 examples = [raw_examples]

            formatted_examples = []
            if examples:
                 for ex in examples:
                     inp = ex.get("input")
                     out = ex.get("output")
                     if inp is not None and out is not None:
                         formatted_examples.append({
                             "input": str(inp),
                             "output": str(out)
                         })

            # 確保 solution 是字串或 None
            if solution and not isinstance(solution, str):
                solution = None # 如果格式不對，設為 None

            # 必須要有 description
            if description and isinstance(description, str) and description.strip():
                all_problems.append(
                    (title, description.strip(), formatted_examples, solution)
                )
            else:
                 print(f"  [警告] {file_path.name} 中索引 {index} 處的題目缺少 'description'。")

        return all_problems

    except Exception as e:
        print(f"  [錯誤] 讀取或解析 {file_path.name} 時發生例外: {e}")
        return [] # 返回空列表表示失敗

# --- (移除 build_code_prompt_with_examples，不再需要) ---


def generate_and_validate(user_need: str, examples: List[Dict[str, str]], solution: Optional[str]) -> Dict[str, Any]:
    """
    (*** 關鍵修改：套用 main.py 邏輯 ***)
    複製 main.py (模式1) 的三階段*生成*邏輯：
    1. Need -> 虛擬碼
    2. Need -> AI 測資 (JSON)
    3. 虛擬碼 + AI 測資 -> 程式碼 
    4. 驗證 (使用 *檔案中的 examples* 來計分)
    """
    result = {
        "success": False,
        "virtual_code": None,
        "generated_code": None,
        "validation_results": [],
        "reference_solution_provided": bool(solution), # 僅記錄，不使用
        "ai_generated_tests": [], # (新) 儲存 AI 生成的測資
        "error": None
    }

    # ---
    # === 階段 1: 生成虛擬碼 (同 main.py) ===
    # ---
    try:
        print("     [階段 1] 正在生成虛擬碼...")
        vc_prompt = build_virtual_code_prompt(user_need) #
        # (修改) 使用 generate_response (同 main.py)
        virtual_code = generate_response(vc_prompt) #
        result["virtual_code"] = virtual_code

        if not virtual_code or not virtual_code.strip():
            print("     [錯誤] 模型未能生成虛擬碼。")
            result["error"] = "Failed to generate virtual code."
            return result

    except Exception as e:
        print(f"     [錯誤] 'generate_response' (虛擬碼階段) 失敗: {e}")
        result["error"] = f"Virtual code generation failed: {e}"
        return result

    # ---
    # === (新) 階段 2: 生成 AI 測資 (同 main.py) ===
    # ---
    ai_generated_tests = []
    try:
        print("     [階段 2] 正在生成 AI 測資 (JSON)...")
        test_prompt = build_test_prompt(user_need) #
        test_resp = generate_response(test_prompt) #
        
        ai_generated_tests = extract_json_block(test_resp) 
        result["ai_generated_tests"] = ai_generated_tests

        if ai_generated_tests:
            print(f"     [提示] 已成功提取 {len(ai_generated_tests)} 筆 AI 測資。")
        else:
            print("     [警告] 未能從模型回覆中提取 JSON 測資。")
    
    except Exception as e:
        print(f"     [錯誤] 'generate_response' (測資階段) 失敗: {e}")
        result["error"] = f"Test case generation failed: {e}"

    # === (新) 階段 3: 依照虛擬碼和 (AI) 測資生成程式碼 (同 main.py) ===
    try:
        print("     [階段 3] 正在根據虛擬碼和 (AI) 測資生成程式碼...")


        code_prompt_string = build_stdin_code_prompt(
            user_need, 
            virtual_code, 
            ai_generated_tests,
            solution=solution,
            file_examples=examples)

        code_resp = call_ollama_cli(code_prompt_string) #

    except Exception as e:
        print(f"     [錯誤] 'generate_response' (程式碼階段) 失敗: {e}")
        result["error"] = f"Code generation failed: {e}"
        return result

    # ---
    # === 階段 4: 提取程式碼 (同 main.py / testrun.py) ===
    # ---
    code = extract_code_block(code_resp) #
    if not code:
        print("     [錯誤] 未能從模型回覆中提取程式碼。")
        result["error"] = "Failed to extract code from model response."
        result["validation_results"].append({
            "example_index": -1,
            "input": None,
            "expected_output": None,
            "success": False,
            "output": code_resp
        })
        return result

    result["generated_code"] = code

    # ---
    # === 階段 5: 驗證 (*** 邏輯保留 testrun.py ***) ===
    # ---
    all_examples_passed = True
    if not examples: 
        print("     [提示] JSON 檔案未提供範例，無法進行輸入輸出驗證。僅檢查程式碼是否可執行。")
        try:
             validation_result = validate_main_function(code, stdin_input="", expected_output=None) #
             success, output_str = validation_result
             result["validation_results"].append({
                 "example_index": 0,
                 "input": "",
                 "expected_output": None,
                 "success": success,
                 "output": output_str
             })
             if success:
                 print("     [成功] 程式碼可執行 ✅")
                 result["success"] = True # (testrun.py 依賴此欄位)
             else:
                 print(f"     [失敗] 執行錯誤 ❌")
                 print(f"       > 實際輸出/錯誤: {repr(output_str)}")
                 result["error"] = "Code failed basic execution check."
                 all_examples_passed = False

        except Exception as e:
            print(f"     [嚴重錯誤] 'validate_main_function' 執行時發生例外: {e}")
            result["error"] = f"Validator crashed during basic execution check: {e}"
            result["validation_results"].append({
                 "example_index": 0,
                 "input": "",
                 "expected_output": None,
                 "success": False,
                 "output": traceback.format_exc()
            })
            all_examples_passed = False
    else:
        print(f"     [階段 4] 正在驗證 {len(examples)} 個 *檔案範例*...")
        for i, ex in enumerate(examples):
            stdin_input = ex['input']
            expected_output = ex['output']
            print(f"       [範例 {i+1}/{len(examples)}] 輸入: {repr(stdin_input)}, 期望輸出: {repr(expected_output)}")

            try:
                # (保留 testrun.py 的比對邏輯)
                validation_result = validate_main_function(code, stdin_input=stdin_input, expected_output=None) #
                exec_success, raw_output_str = validation_result
                
                success = False
                output_to_store = raw_output_str 

                if exec_success:
                    # (修改) 使用從 core 導入的 _normalize_output
                    norm_expected = _normalize_output(expected_output) #
                    norm_actual = _normalize_output(raw_output_str) #
                    
                    if norm_expected == norm_actual:
                        success = True
                    else:
                        output_to_store = (
                            f"[Output Mismatch (Normalized)]\n"
                            f"Expected (Norm): {repr(norm_expected)}\n"
                            f"Got (Norm):      {repr(norm_actual)}\n"
                            f"--- (Raw) ---\n"
                            f"Raw Expected: {repr(expected_output)}\n"
                            f"Raw Got:      {repr(raw_output_str)}"
                        )
                else:
                    pass 
                
                result["validation_results"].append({
                    "example_index": i,
                    "input": stdin_input,
                    "expected_output": expected_output,
                    "success": success,
                    "output": output_to_store
                })

                if success:
                    print(f"       [成功] 範例 {i+1} 通過 ✅")
                else:
                    print(f"       [失敗] 範例 {i+1} 失敗 ❌")
                    print(f"         > 期望 (Raw): {repr(expected_output)}")
                    print(f"         > 實際 (Raw): {repr(raw_output_str)}")
                    if exec_success: 
                        print(f"         > 期望 (Norm): {repr(_normalize_output(expected_output))}")
                        print(f"         > 實際 (Norm): {repr(_normalize_output(raw_output_str))}")
                    all_examples_passed = False

            except Exception as e:
                print(f"       [嚴重錯誤] 'validate_main_function' 對範例 {i+1} 執行時發生例外: {e}")
                result["error"] = f"Validator crashed on example {i+1}: {e}"
                result["validation_results"].append({
                    "example_index": i,
                    "input": stdin_input,
                    "expected_output": expected_output,
                    "success": False,
                    "output": traceback.format_exc()
                })
                all_examples_passed = False

    if all_examples_passed:
        result["success"] = True # (testrun.py 依賴此欄位)
        print("     [總結] 所有 *檔案範例* 驗證通過 ✅")
    else:
         result["success"] = False # (testrun.py 依賴此欄位)
         if examples:
             print("     [總結] 部分或全部 *檔案範例* 驗證失敗 ❌")

    return result

if __name__ == "__main__":

    # (此主迴圈保持不變，它現在會呼叫上面修改過的 generate_and_validate)

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 (已套用 main.py 生成邏輯) ---")

    result_dir = script_dir / "result_pro"
    result_dir.mkdir(parents=True, exist_ok=True)
    print(f"輸出目錄: {result_dir}")

    overall_start_time = time.time()

    for run_index in range(41, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")

        start_time = time.time()

        DATA_DIR = script_dir / "test"  
        FULL_RESULTS_FILE = result_dir / f"results_run_{run_index}.json"
        ERROR_SUMMARY_FILE = result_dir / f"summary_run_{run_index}.json"

        if not DATA_DIR.is_dir():
            print(f"[嚴重錯誤] 找不到 'data' 目錄於: {DATA_DIR}")
            print(f"--- 第 {run_index} 次循環失敗(Data Dir Not Found) ---")
            continue

        print(f"--- 開始遍歷 {DATA_DIR} ---")

        all_results: List[Dict[str, Any]] = []
        files_processed = 0
        files_skipped = 0 
        files_failed_load = 0

        json_files = list(DATA_DIR.rglob("*.json"))
        total_files = len(json_files)
        print(f"總共找到 {total_files} 個 .json 檔案。")

        for file_path in json_files:
            relative_path = file_path.relative_to(DATA_DIR) 

            # (過濾邏輯保持不變)
            if file_path.name == "leetcode_index.json":
                files_skipped += 1
                continue
            if relative_path.parts and relative_path.parts[0] == 'lessons':
                files_skipped += 1
                continue
            if file_path.name == "README.md":
                 files_skipped += 1
                 continue
            
            print(f"\n--- 正在處理檔案 ({files_processed + 1}/{total_files}): {relative_path} ---")

            # 3. 載入檔案中的 *所有* 題目
            all_problems_in_file = load_all_problems_from_file(file_path)

            if not all_problems_in_file:
                files_failed_load += 1
                print(f"  [載入失敗] 無法從此檔案解析出任何有效的題目。")
                
                problem_result = {
                    "source_file": str(relative_path),
                    "problem_index_in_file": -1,
                    "title": file_path.stem,
                    "generation_result": {
                        "success": False,
                        "error": "Could not parse any valid problems from this file."
                    }
                }
                all_results.append(problem_result)
                files_processed += 1
                continue

            print(f"  [載入成功] 於 {relative_path} 中找到 {len(all_problems_in_file)} 道題目。")

            for problem_index, (title, description, examples, solution) in enumerate(all_problems_in_file):
                
                print(f"    --- 處理題目 {problem_index + 1}/{len(all_problems_in_file)}: {title} ---")

                problem_result = {
                    "source_file": str(relative_path),
                    "problem_index_in_file": problem_index,
                    "title": title,
                    "description_snippet": description[:100] + "...",
                    "examples_loaded": len(examples),
                    "reference_solution_found": bool(solution),
                    "generation_result": None,
                }

                # 4. 為 *這道題目* 生成並驗證 (呼叫修改後的函式)
                gen_result = generate_and_validate(description, examples, solution)
                problem_result["generation_result"] = gen_result

                all_results.append(problem_result)
            
            files_processed += 1

        # 6. 寫入 JSON 輸出 (邏輯不變)
        print("\n--- 處理完成 ---")
        try:
            with open(FULL_RESULTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
            print(f"\n[成功] 完整結果已儲存至: {FULL_RESULTS_FILE}")
        except Exception as e:
            print(f"\n[嚴重錯誤] 將完整結果寫入 JSON 失敗: {e}")

        # 7. 產生並寫入錯誤總結 (邏輯不變)
        success_count = 0
        failed_cases = [] 

        for item in all_results:
            gen_result = item.get("generation_result", {})
            
            if item.get("problem_index_in_file") == -1:
                 failed_cases.append({
                    "title": item.get("title", "N/A"),
                    "source_file": item.get("source_file", "N/A"),
                    "problem_index_in_file": -1,
                    "generation_error": gen_result.get("error"),
                    "failed_validation_details": [],
                    "generated_code": None,
                    "virtual_code": None,
                 })
                 continue

            if gen_result.get("success") is True:
                success_count += 1
            else:
                failed_example_details = []
                validation_results = gen_result.get("validation_results", [])
                for vr in validation_results:
                    if vr.get("success") is False:
                         failed_example_details.append({
                              "example_index": vr.get("example_index", -1),
                              "input": vr.get("input"),
                              "expected_output": vr.get("expected_output"),
                              "actual_output_or_error": vr.get("output")
                         })

                failed_cases.append({
                    "title": item.get("title", "N/A"),
                    "source_file": item.get("source_file", "N/A"),
                    "problem_index_in_file": item.get("problem_index_in_file"),
                    "generation_error": gen_result.get("error"),
                    "failed_validation_details": failed_example_details,
                    "generated_code": gen_result.get("generated_code"),
                    "virtual_code": gen_result.get("virtual_code"),
                })

        num_attempted_gen = len(all_results) 
        num_failed_gen = len(failed_cases)

        error_summary = {
            "run_index": run_index,
            "total_files_found": total_files,
            "total_files_processed": files_processed,
            "files_skipped": files_skipped,
            "files_failed_load": files_failed_load,
            "---": "--- (以下基於 *題目* 總數) ---",
            "total_problems_attempted": num_attempted_gen,
            "generation_and_validation_success_count": success_count,
            "generation_or_validation_failure_count": num_failed_gen,
            "failed_cases_details": failed_cases
        }

        try:
            with open(ERROR_SUMMARY_FILE, 'w', encoding='utf-8') as f:
                json.dump(error_summary, f, indent=2, ensure_ascii=False)
            print(f"[成功] 錯誤總結已儲存至: {ERROR_SUMMARY_FILE}")
        except Exception as e:
            print(f"[嚴重錯誤] 將錯誤總結寫入 JSON 失敗: {e}")

        # 8. 輸出總結 (邏輯不變)
        end_time = time.time()

        print(f"\n--- 第 {run_index} / {TOTAL_RUNS} 次循環總結 ---")
        print(f"此次循環耗時: {end_time - start_time:.2f} 秒")
        print(f"總檔案數 (Found): {total_files}")
        print(f"總檔案數 (Processed): {files_processed}")
        print(f"總檔案數 (Skipped): {files_skipped}")
        print(f"總檔案數 (Load Failed): {files_failed_load}")
        print("---")
        print(f"嘗試生成總 *題數*: {num_attempted_gen}")
        print(f"生成且驗證成功 (題數): {success_count}")
        print(f"生成或驗證失敗 (題數): {num_failed_gen}")
        print(f"=============================================")

    overall_end_time = time.time()
    print(f"\n--- 所有 {TOTAL_RUNS} 次循環已全部完成 ---")
    print(f"總共耗時: {overall_end_time - overall_start_time:.2f} 秒")
    print(f"所有結果已儲存於 {result_dir} 資料夾中。")