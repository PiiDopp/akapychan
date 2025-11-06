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
    from core import (
        generate_response, 
        extract_code_block, 
        extract_json_block,
        validate_main_function, # 我們將用它來驗證 Solution
        _normalize_output
    )
    from core.model_interface import (
        build_virtual_code_prompt,
        build_test_prompt,
        build_stdin_code_prompt, # 雖然我們不用它生成程式碼了，但保留導入
        call_ollama_cli
    )

except ImportError as e:
    print(f"[嚴重錯誤] 導入 'core' 模組時發生錯誤: {e}")
    print("請確保 core/__init__.py, core/model_interface.py, core/code_extract.py, core/validators.py 均存在。")
    exit(1)
# --- 導入結束 ---


def load_all_problems_from_file(file_path: pathlib.Path) -> List[Tuple[str, str, List[Dict[str, str]], Optional[str]]]:
    """
    (此函式保持不變)
    """
    all_problems = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        default_title = file_path.stem
        problems_list = []

        if "coding_practice" in data and isinstance(data["coding_practice"], list):
            problems_list = data["coding_practice"]
        elif "description" in data or "solution" in data:
            problems_list = [data]

        if not problems_list:
            print(f"  [警告] 在 {file_path.name} 中找不到 'coding_practice' 列表或有效的頂層題目。")
            return []

        for index, problem in enumerate(problems_list):
            if not isinstance(problem, dict):
                print(f"  [警告] {file_path.name} 中索引 {index} 處的項目不是一個有效的物件（字典）。")
                continue

            title = problem.get("title", f"{default_title}_problem_{index+1}")
            description = problem.get("description", problem.get("content"))
            solution = problem.get("solution")
            raw_examples = problem.get("examples")
            examples = []

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
                        if "無" not in str(inp):
                             formatted_examples.append({
                                "input": str(inp),
                                "output": str(out)
                             })
                        else:
                            formatted_examples.append({
                                "input": "", 
                                "output": str(out)
                            })


            if solution and not isinstance(solution, str):
                solution = None

            if description and isinstance(description, str) and description.strip():
                all_problems.append(
                    (title, description.strip(), formatted_examples, solution)
                )
            else:
                print(f"  [警告] {file_path.name} 中索引 {index} 處的題目缺少 'description'。")

        return all_problems

    except Exception as e:
        print(f"  [錯誤] 讀取或解析 {file_path.name} 時發生例外: {e}")
        return []

def _wrap_solution_as_main(solution_code: str, has_stdin: bool) -> str:
    """
    (*** 輔助函式 - 已修正縮排問題 ***)
    將 data/ 檔案中的 solution 片段包裝成可執行的 main 腳本。
    """
    # 1. 檢查是否已經有 main 區塊
    if "if __name__ == \"__main__\":" in solution_code:
        return solution_code
    
    # 2. 檢查是否已經是頂層可執行程式碼 (例如 1000.json 的情況)
    #    如果它不使用 input() 也不使用 sys.stdin，
    #    且 has_stdin 為 False，我們就假設它直接執行。
    uses_input = "input(" in solution_code or "sys.stdin" in solution_code
    if not has_stdin and not uses_input:
        return solution_code # 例如 1000.json，直接執行

    # 3. 對於所有其他片段 (需要 stdin 或有函式定義)，
    #    我們將它們包裝在 main 區塊中並 *正確縮排*。
    
    imports = ""
    # 確保導入 time (用於 800.json 的 time.sleep)
    if "time." in solution_code and "import time" not in solution_code:
        imports += "import time\n"
    # 確保導入 sys (用於 sys.stdin)
    if "sys." in solution_code and "import sys" not in solution_code:
        imports += "import sys\n"
    
    
    # (*** 關鍵修正 ***)
    # 將 solution_code 的 *每一行* 都縮排 4 個空格
    indented_solution = "\n".join(["    " + line for line in solution_code.splitlines()])

    wrapped_code = f"""
{imports}
import sys 
import time 

def main_logic():
    # --- 開始 Solution 程式碼 ---
{indented_solution}
    # --- 結束 Solution 程式碼 ---

if __name__ == "__main__":
    main_logic()
"""
    return wrapped_code


def generate_and_validate(user_need: str, examples: List[Dict[str, str]], solution: Optional[str]) -> Dict[str, Any]:
    """
    (*** 此函式保持不變 ***)
    (*** 模式：驗證 AI 測資 ***)
    1. (移除) 虛擬碼
    2. Need -> AI 測資 (JSON)
    3. (移除) 程式碼生成
    4. 驗證 (使用 *AI 生成的測資* 來驗證 *檔案中的 Solution*)
    """
    result = {
        "success": False, # 最終成功 = 所有 AI 測資都通過 Solution 驗證
        "virtual_code": None, # (保留欄位，設為 N/A)
        "generated_code": None, # (保留欄位，設為 N/A)
        "validation_results": [], # 儲存對 Solution 的驗證結果
        "reference_solution_provided": bool(solution),
        "ai_generated_tests": [], # (關鍵) 儲存 AI 生成的測資
        "error": None
    }

    # ---
    # === (新) 階段 1: 檢查是否有 Solution 可供驗證 ===
    # ---
    if not solution or not solution.strip():
        print("     [錯誤] 檔案中未提供參考解法 (Solution)，無法驗證 AI 測資。")
        result["error"] = "Skipped: No reference solution found in file."
        return result

    # ---
    # === 階段 2: 生成 AI 測資 (同 main.py) ===
    # ---
    ai_generated_tests = []
    try:
        print("     [階段 2] 正在生成 AI 測資 (JSON)...")
        test_prompt = build_test_prompt(user_need) 
        test_resp = generate_response(test_prompt) 
        
        ai_generated_tests = extract_json_block(test_resp) 
        result["ai_generated_tests"] = ai_generated_tests

        if ai_generated_tests:
            print(f"     [提示] 已成功提取 {len(ai_generated_tests)} 筆 AI 測資。")
        else:
            print("     [警告] 未能從模型回覆中提取 JSON 測資。")
            result["error"] = "Failed to extract AI-generated test cases (JSON)."
            return result 

    except Exception as e:
        print(f"     [錯誤] 'generate_response' (測資階段) 失敗: {e}")
        result["error"] = f"Test case generation failed: {e}"
        return result

    # ---
    # === (移除) 階段 1 & 3 (虛擬碼與程式碼生成) ===
    # ---
    result["virtual_code"] = "N/A (Testrun Mode: Validate AI Tests)"
    result["generated_code"] = "N/A (Testrun Mode: Validate AI Tests)"


    # ---
    # === (新) 階段 3: 驗證 (使用 AI 測資 vs 檔案 Solution) ===
    # ---
    all_ai_tests_passed = True
    
    has_real_stdin_in_examples = any(ex.get("input", "") != "" for ex in examples)
    
    try:
        # (*** 呼叫修正版的 Wrapper ***)
        executable_solution = _wrap_solution_as_main(solution, has_real_stdin_in_examples)
    except Exception as e:
        print(f"     [嚴重錯誤] 包裝 Solution 時發生例外: {e}")
        result["error"] = f"Failed to wrap solution code: {e}"
        return result

    print(f"     [階段 3] 正在使用 {len(ai_generated_tests)} 筆 *AI 測資* 驗證 *檔案 Solution*...")

    for i, ai_test in enumerate(ai_generated_tests):
        
        stdin_input = None
        expected_output = None

        if isinstance(ai_test, list) and len(ai_test) == 2:
            stdin_input = str(ai_test[0])
            expected_output = str(ai_test[1])
        elif isinstance(ai_test, dict):
            stdin_input = str(ai_test.get("input", ""))
            expected_output = str(ai_test.get("output", ""))
        else:
            print(f"       [警告] AI 測資 {i+1} 格式不符 (非 list[2] 或 dict): {ai_test}")
            result["validation_results"].append({
                "ai_test_index": i,
                "input": None,
                "expected_output": None,
                "success": False,
                "output": f"Invalid AI test case format: {ai_test}"
            })
            all_ai_tests_passed = False
            continue

        print(f"       [AI 測資 {i+1}/{len(ai_generated_tests)}] 輸入: {repr(stdin_input)}, 期望輸出: {repr(expected_output)}")

        try:
            validation_result = validate_main_function(executable_solution, stdin_input=stdin_input, expected_output=None) 
            exec_success, raw_output_str = validation_result
            
            success = False
            output_to_store = raw_output_str 

            if exec_success:
                norm_expected = _normalize_output(expected_output)
                norm_actual = _normalize_output(raw_output_str)
                
                if norm_expected == norm_actual:
                    success = True
                else:
                    output_to_store = (
                        f"[Output Mismatch (Normalized)]\n"
                        f"AI Expected (Norm): {repr(norm_expected)}\n"
                        f"Solution Got (Norm):{repr(norm_actual)}\n"
                        f"--- (Raw) ---\n"
                        f"AI Expected (Raw): {repr(expected_output)}\n"
                        f"Solution Got (Raw): {repr(raw_output_str)}"
                    )
            else:
                pass 
            
            result["validation_results"].append({
                "ai_test_index": i,
                "input": stdin_input,
                "expected_output": expected_output,
                "success": success,
                "output": output_to_store 
            })

            if success:
                print(f"       [成功] AI 測資 {i+1} 通過 (Solution 執行正確) ✅")
            else:
                print(f"       [失敗] AI 測資 {i+1} 失敗 (Solution 輸出不符) ❌")
                print(f"         > AI 期望 (Raw): {repr(expected_output)}")
                print(f"         > Solution 輸出 (Raw): {repr(raw_output_str)}")
                if exec_success: 
                    print(f"         > AI 期望 (Norm): {repr(_normalize_output(expected_output))}")
                    print(f"         > Solution 輸出 (Norm): {repr(_normalize_output(raw_output_str))}")
                all_ai_tests_passed = False

        except Exception as e:
            print(f"       [嚴重錯誤] 'validate_main_function' 對 AI 測資 {i+1} 執行 Solution 時發生例外: {e}")
            result["error"] = f"Validator crashed (running Solution) on AI test {i+1}: {e}"
            result["validation_results"].append({
                "ai_test_index": i,
                "input": stdin_input,
                "expected_output": expected_output,
                "success": False,
                "output": traceback.format_exc()
            })
            all_ai_tests_passed = False


    if all_ai_tests_passed:
        result["success"] = True 
        print("     [總結] 所有 *AI 測資* 均通過 *檔案 Solution* 驗證 ✅")
    else:
        result["success"] = False 
        if ai_generated_tests:
            print("     [總結] 部分或全部 *AI 測資* 驗證失敗 ❌")

    return result

if __name__ == "__main__":

    # (主迴圈保持不變)

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 (*** 模式：驗證 AI 測資 vs 檔案 Solution ***) ---")

    result_dir = script_dir / "results_ai_test_validation" 
    result_dir.mkdir(parents=True, exist_ok=True)
    print(f"輸出目錄: {result_dir}")

    overall_start_time = time.time()

    for run_index in range(1, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")

        start_time = time.time()

        DATA_DIR = script_dir / "data"  
        
        FULL_RESULTS_FILE = result_dir / f"results_ai_validation_run_{run_index}.json"
        ERROR_SUMMARY_FILE = result_dir / f"summary_ai_validation_run_{run_index}.json"

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
                    "examples_loaded_count": len(examples), 
                    "reference_solution_found": bool(solution),
                    "validation_of_ai_tests_result": None, 
                }

                gen_result = generate_and_validate(description, examples, solution)
                problem_result["validation_of_ai_tests_result"] = gen_result

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
            gen_result = item.get("validation_of_ai_tests_result", {})
            
            if item.get("problem_index_in_file") == -1:
                failed_cases.append({
                    "title": item.get("title", "N/A"),
                    "source_file": item.get("source_file", "N/A"),
                    "problem_index_in_file": -1,
                    "error": gen_result.get("error"), 
                    "failed_validation_details": [],
                    "ai_generated_tests": None, 
                    "reference_solution_found": item.get("reference_solution_found"),
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
                            "ai_test_index": vr.get("ai_test_index", -1), 
                            "input": vr.get("input"),
                            "ai_expected_output": vr.get("expected_output"), 
                            "solution_actual_output_or_error": vr.get("output") 
                        })

                failed_cases.append({
                    "title": item.get("title", "N/A"),
                    "source_file": item.get("source_file", "N/A"),
                    "problem_index_in_file": item.get("problem_index_in_file"),
                    "error": gen_result.get("error"), 
                    "failed_validation_details": failed_example_details,
                    "ai_generated_tests": gen_result.get("ai_generated_tests"), 
                    "reference_solution_found": item.get("reference_solution_found"),
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
            "ai_test_validation_success_count": success_count, 
            "ai_test_validation_failure_count": num_failed_gen, 
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
        print(f"嘗試驗證總 *題數*: {num_attempted_gen}")
        print(f"AI 測資驗證成功 (題數): {success_count}")
        print(f"AI 測資驗證失敗 (題數): {num_failed_gen}")
        print(f"=============================================")

    overall_end_time = time.time()
    print(f"\n--- 所有 {TOTAL_RUNS} 次循環已全部完成 ---")
    print(f"總共耗時: {overall_end_time - overall_start_time:.2f} 秒")
    print(f"所有結果已儲存於 {result_dir} 資料夾中。")