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
    # (修改) 僅導入實際需要的函式
    from core import (
        generate_response, 
        _normalize_output      # <-- (保留)
    )
    # (移除) 不再需要 main.py 模式 1 的函式
    # from core.model_interface import (...)

except ImportError as e:
    print(f"[嚴重錯誤] 導入 'core' 模組時發生錯誤: {e}")
    print("請確保 core/__init__.py, core/validators.py 均存在。")
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


def build_solve_from_input_prompt(user_need: str, stdin_input: str) -> str:
    """
    (新) 建立一個提示，要求 AI 根據*需求*和*輸入*來*解決*問題並預測輸出。
    (不提供程式碼)
    (*** V2: 強化限制，禁止輸出程式碼 ***)
    """
    prompt_lines = [
        "用繁體中文回答。\n"
        "你是一個 Python 程式*執行模擬器* (Runtime Simulator)。\n"
        "任務：你將收到一個「程式需求」和一段「標準輸入 (stdin)」。\n"
        "請*模擬*執行該需求，並*只*輸出程式會印到「標準輸出 (stdout)」的*最終結果*。\n\n"
        "**⚠️ 絕對禁止 ⚠️**：\n"
        "1.  **禁止**輸出任何 Python 程式碼 (例如 `print(...)`, `input()`, `def ...`)。\n"
        "2.  **禁止**輸出任何解釋、註解、或 \"```\" 標記。\n\n"
        "**重要規則**：\n"
        "1.  **僅輸出 stdout**：只輸出程式執行後會顯示在終端機上的*確切文字*。\n"
        "2.  **精確模擬**：完全依照需求和輸入。如果輸出包含換行符 (\\n)，你的輸出也必須包含。\n"
        "3.  **處理空輸入/輸出**：如果 'stdin' 是空的，就模擬空輸入。如果需求*不會*印出任何東西，就*不要*輸出任何文字（返回一個空字串）。\n\n"
        "--- 程式需求 (Description) ---\n"
        f"{user_need}\n\n"
        "--- 標準輸入 (stdin) ---\n"
        f"{repr(stdin_input)}\n"
        "\n"
        "--- 預測的標準輸出 (stdout) 開始 (請勿包含任何程式碼或註解) ---"
    ]
    return "".join(prompt_lines)


def generate_and_validate(user_need: str, examples: List[Dict[str, str]], solution: Optional[str]) -> Dict[str, Any]:
    """
    (*** 關鍵修改：移除程式碼生成，僅*預測*輸出 ***)
    1. [移除] 虛擬碼
    2. [移除] AI 測資
    3. [移除] 程式碼生成
    4. [修改] 驗證 (使用 *檔案中的 examples*，要求 AI *僅根據需求和輸入* 預測輸出並比對)
    """
    result = {
        "success": False,
        # (移除) "virtual_code": None,
        # (移除) "generated_code": None,
        "validation_results": [],
        "reference_solution_provided": bool(solution), # 僅記錄
        # (移除) "ai_generated_tests": [], 
        "error": None
    }

    # ---
    # === [*** 修改 ***] 階段 5: 使用 AI *僅* 預測輸出並驗證 ===
    # (移除 1-4 階段)
    # ---
    all_examples_passed = True
    if not examples: 
        print("     [提示] JSON 檔案未提供範例，無法進行輸入輸出驗證。僅 *預測* (空輸入) 的輸出。")
        try:
            # [修改] 使用 build_solve_from_input_prompt
            predict_prompt = build_solve_from_input_prompt(user_need, "")
            predicted_output_str = generate_response(predict_prompt)
            
            # 假設空輸入應該產生空輸出
            norm_expected = ""
            norm_actual = _normalize_output(predicted_output_str)
            success = (norm_expected == norm_actual)

            result["validation_results"].append({
                "example_index": 0,
                "input": "",
                "expected_output": "", # 假設期望為空
                "success": success,
                "output": predicted_output_str # 儲存 AI 預測的輸出
            })
            
            if success:
                print("     [成功] (空輸入) 預測輸出為空 ✅")
                result["success"] = True 
            else:
                print(f"     [失敗] 預測 (空輸入) 錯誤 ❌")
                print(f"       > 預測的輸出/錯誤: {repr(predicted_output_str)}")
                result["error"] = "Prediction failed (non-empty output for empty input)."
                all_examples_passed = False

        except Exception as e:
            print(f"     [嚴重錯誤] 'generate_response' (預測階段) 執行時發生例外: {e}")
            result["error"] = f"Predictor crashed during basic execution check: {e}"
            result["validation_results"].append({
                "example_index": 0,
                "input": "",
                "expected_output": "",
                "success": False,
                "output": traceback.format_exc()
            })
            all_examples_passed = False
    else:
        print(f"     [階段 5 (修改)] 正在 *預測* {len(examples)} 個 *檔案範例* 的輸出 (不生成程式碼)...")
        for i, ex in enumerate(examples):
            stdin_input = ex['input']
            expected_output = ex['output']
            print(f"       [範例 {i+1}/{len(examples)}] 輸入: {repr(stdin_input)}, 期望輸出: {repr(expected_output)}")

            try:
                # [修改] 移除 validate_main_function，改用 AI 預測
                # 1. 建立預測 prompt
                predict_prompt = build_solve_from_input_prompt(user_need, stdin_input)
                # 2. 呼叫 AI 取得預測的輸出
                raw_output_str = generate_response(predict_prompt)
                # 3. 假設 AI 呼叫本身是成功的 (錯誤會被印在 raw_output_str 中)
                exec_success = True 
                
                success = False
                output_to_store = raw_output_str 

                if exec_success: # (這個 exec_success 只是代表 AI 成功回覆)
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
                            f"Raw Got (Predicted): {repr(raw_output_str)}"
                        )
                
                result["validation_results"].append({
                    "example_index": i,
                    "input": stdin_input,
                    "expected_output": expected_output,
                    "success": success,
                    "output": output_to_store # 儲存 AI 預測的輸出 (或錯誤比對)
                })

                if success:
                    print(f"       [成功] 範例 {i+1} 預測通過 ✅")
                else:
                    print(f"       [失敗] 範例 {i+1} 預測失敗 ❌")
                    print(f"         > 期望 (Raw): {repr(expected_output)}")
                    print(f"         > 預測 (Raw): {repr(raw_output_str)}")
                    if exec_success: 
                        print(f"         > 期望 (Norm): {repr(_normalize_output(expected_output))}")
                        print(f"         > 預測 (Norm): {repr(_normalize_output(raw_output_str))}")
                    all_examples_passed = False

            except Exception as e:
                print(f"       [嚴重錯誤] 'generate_response' (預測階段) 對範例 {i+1} 執行時發生例外: {e}")
                result["error"] = f"Predictor crashed on example {i+1}: {e}"
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
        print("     [總結] 所有 *檔案範例* 預測驗證通過 ✅")
    else:
        result["success"] = False # (testrun.py 依賴此欄位)
        if examples:
            print("     [總結] 部分或全部 *檔案範例* 預測驗證失敗 ❌")

    return result

if __name__ == "__main__":

    # (此主迴圈保持不變，它現在會呼叫上面修改過的 generate_and_validate)

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 (僅預測輸出，不生成程式碼) ---") # [修改] 更新標題

    result_dir = script_dir / "results_solve_from_input" # [修改] 變更輸出資料夾
    result_dir.mkdir(parents=True, exist_ok=True)
    print(f"輸出目錄: {result_dir}")

    overall_start_time = time.time()

    for run_index in range(1, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")

        start_time = time.time()

        DATA_DIR = script_dir / "data" # [修改] 根據請求，改回 data (因為 data_original 裡面沒有 lessons)
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
            # [修改] 移除 'lessons' 過濾，因為 data/lessons/ 存在
            # if relative_path.parts and relative_path.parts[0] == 'lessons':
            #     files_skipped += 1
            #     continue
            if relative_path.parts and relative_path.parts[0] == 'Leetcode': # [修改] data/Leetcode 存在
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
                    # (移除) "generated_code": None,
                    # (移除) "virtual_code": None,
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
                    # (移除) "generated_code": gen_result.get("generated_code"),
                    # (移除) "virtual_code": gen_result.get("virtual_code"),
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
            "prediction_success_count": success_count, # [修改]
            "prediction_failure_count": num_failed_gen, # [修改]
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
        print(f" *預測* 驗證成功 (題數): {success_count}") # [修改]
        print(f" *預測* 驗證失敗 (題數): {num_failed_gen}") # [修改]
        print(f"=============================================")

    overall_end_time = time.time()
    print(f"\n--- 所有 {TOTAL_RUNS} 次循環已全部完成 ---")
    print(f"總共耗時: {overall_end_time - overall_start_time:.2f} 秒")
    print(f"所有結果已儲存於 {result_dir} 資料夾中。")