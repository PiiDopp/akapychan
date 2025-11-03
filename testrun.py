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

def _normalize_output(s: str) -> str:
    """
    (*** 第 2 版修改 ***)
    輔助函數：將 stdout 和 expected output 字串標準化以便進行比較。
    1. 去除字串前後的空白字元 (strip)。
    2. 去除最外層匹配的單引號或雙引號 (解決 "'bab'" vs "bab")。
    3. (新增) 將所有「內部」單引號替換為雙引號 (解決 "['a']" vs "[\"a\"]")。
    4. 去除所有「內部」空格 (解決 "[0, 1]" vs "[0,1]")。
    """
    if not isinstance(s, str):
        return str(s) # 如果輸入不是字串，轉換它

    s = s.strip()

    # 1. 去除最外層的引號 (e.g., "'bab'" -> "bab" 或 "['...']" -> ['...'])
    if len(s) >= 2:
        if s.startswith("'") and s.endswith("'"):
            s = s[1:-1]
        elif s.startswith('"') and s.endswith('"'):
            s = s[1:-1]

    # 2. (*** 新增 ***) 標準化所有內部引號為雙引號
    #    這會將 Python 的 "['255...']" 轉換為 "[\"255...\"]"
    s = s.replace("'", '"')

    # 3. 去除所有內部的空格 (e.g., "[0, 1]" -> "[0,1]")
    s = s.replace(" ", "")

    return s


# --- 導入 Core 模組 (遵守使用者限制) ---
try:
    # (限制) 只能從 model_interface.py 導入模型相關函式
    from core.model_interface import build_code_prompt, call_ollama_cli, build_virtual_code_prompt

    # (允許) 導入 extract_code_block 輔助函式
    from core import extract_code_block

    # (允許) 導入 validate_main_function 輔助函式
    from core import validate_main_function

except ImportError as e:
    print(f"[嚴重錯誤] 導入 'core' 模組時發生錯誤: {e}")
    print("請確保 core/__init__.py, core/model_interface.py, core/code_extract.py, core/validators.py 均存在。")
    exit(1)
# --- 導入結束 ---


def load_all_problems_from_file(file_path: pathlib.Path) -> List[Tuple[str, str, List[Dict[str, str]], Optional[str]]]:
    """
    (*** 重大修改 ***)
    從指定的 JSON 檔案彈性載入 *所有* 練習題的需求描述、範例和參考解法。
    
    返回一個元組的 *列表*：
    List[ (title, description, examples, solution), ... ]
    
    如果檔案無法解析或未找到任何題目，則返回一個空列表。
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

# --- 新增：輔助函數來構建包含範例的提示 ---
# (此函數保持不變)
def build_code_prompt_with_examples(description: str, examples: List[Dict[str, str]]) -> str:
    """構建程式碼生成的提示，包含範例執行要求。"""
    prompt = f"請根據以下描述生成 Python 程式碼：\n\n{description}\n\n"
    prompt += "生成的程式碼必須包含一個 `if __name__ == \"__main__\":` 區塊。\n"
    if examples:
        prompt += "在這個 main 區塊中，你需要模擬執行以下範例，確保程式能處理對應的輸入並產生完全相同的輸出：\n"
        for i, ex in enumerate(examples):
            # 處理多行輸入
            inp_lines = ex['input'].split('\\n')
            inp_repr = repr(ex['input']) # 使用 repr 顯示換行符
            out_repr = repr(ex['output'])

            prompt += f"\n--- 範例 {i+1} ---\n"
            if len(inp_lines) > 1:
                 prompt += f"輸入 (多行):\n{ex['input']}\n"
            else:
                 prompt += f"輸入: {inp_repr}\n"
            prompt += f"期望輸出: {out_repr}\n"
            prompt += f"請在 main 中加入處理此輸入並打印輸出的程式碼。\n"
        prompt += "\n請確保打印的輸出格式與期望輸出完全一致，包括換行符和空格。\n"
    else:
        prompt += "由於沒有提供範例，請確保程式碼結構完整，包含 `if __name__ == \"__main__\":` 區塊但可以留空或只放 `pass`。\n"

    prompt += "\n請將完整的 Python 程式碼放在 ```python ... ``` 區塊中。"
    return prompt
# --- 提示輔助函數結束 ---


def generate_and_validate(user_need: str, examples: List[Dict[str, str]], solution: Optional[str]) -> Dict[str, Any]:
    """
    (*** 關鍵修改 ***)
    複製 main.py (模式1) 的兩階段生成邏輯，並加入範例驗證和參考解法：
    1. Need -> 虛擬碼
    2. 虛擬碼 + Examples + Solution -> 程式碼 (包含 main 執行範例)
    3. 驗證 (M 模式，使用 JSON 中的 examples)
    
    (此函數邏輯保持不變，因為它本來就是處理單一問題)
    """
    result = {
        "success": False,
        "virtual_code": None,
        "generated_code": None,
        "validation_results": [],
        "reference_solution_provided": bool(solution),
        "error": None
    }

    # ---
    # === 階段 1: 生成虛擬碼 (同之前) ===
    # ---
    try:
        print("     [階段 1] 正在生成虛擬碼...")
        vc_prompt = build_virtual_code_prompt(user_need) # 虛擬碼提示不變
        vc_resp = call_ollama_cli(vc_prompt)
        virtual_code = vc_resp # 直接使用模型回覆，可能包含 ```
        result["virtual_code"] = virtual_code

        if not virtual_code or not virtual_code.strip():
            print("     [錯誤] 模型未能生成虛擬碼。")
            result["error"] = "Failed to generate virtual code."
            return result

    except Exception as e:
        print(f"     [錯誤] 'call_ollama_cli' (虛擬碼階段) 失敗: {e}")
        result["error"] = f"Virtual code generation failed: {e}"
        return result

    # ---
    # === 階段 2: 依照虛擬碼、範例和參考解法生成程式碼 ===
    # ---
    try:
        print("     [階段 2] 正在根據虛擬碼、範例及參考解法生成程式碼...")

        # *** 修改：動態構建包含 solution 的提示 ***
        code_prompt_lines = [
            "用繁體中文回答。\n你是程式碼生成助理。\n任務：依據使用者需求、虛擬碼、範例，並參考提供的解法，產生正確可執行的 Python 程式碼，並加上白話註解。\n",
            f"原始需求：\n{user_need}\n",
            f"虛擬碼：\n{virtual_code}\n", # 使用模型生成的虛擬碼
            "生成的程式碼必須包含一個 `if __name__ == \"__main__\":` 區塊。\n",
            # --- START OF MODIFICATION (修正提示) ---
            "這個 `main` 區塊必須：\n"
            "1. 從標準輸入 (stdin) 讀取解決問題所需的所有數據（例如，使用 `input()` 或 `sys.stdin.read()`）。\n"
            "2. 處理這些數據。\n"
            "3. 將最終答案打印 (print) 到標準輸出 (stdout)。\n"
            "4. **不要** 在 `main` 區塊中硬編碼 (hard-code) 任何範例輸入或輸出。\n"
        ]

        if examples:
            code_prompt_lines.append("\n以下是幾個範例，展示了程式執行時**應該**如何處理輸入和輸出（你的程式碼將透過 `stdin` 接收這些輸入）：\n")
            for i, ex in enumerate(examples):
                inp_repr = repr(ex['input'])
                out_repr = repr(ex['output'])
                code_prompt_lines.append(f"--- 範例 {i+1} ---")
                code_prompt_lines.append(f"若 stdin 輸入為: {inp_repr}")
                code_prompt_lines.append(f"則 stdout 輸出應為: {out_repr}")
            code_prompt_lines.append("\n再次強調：你的 `main` 程式碼不應該包含這些範例，它應該是通用的，能從 `stdin` 讀取任何合法的輸入。\n")
        else:
            code_prompt_lines.append("由於沒有提供範例，請確保程式碼結構完整，包含 `if __name__ == \"__main__\":` 區塊並能從 `stdin` 讀取數據。\n")


        # <<< 新增：如果存在 solution，加入提示 >>>
        if solution:
            code_prompt_lines.append("您可以參考以下的參考解法：\n")
            code_prompt_lines.append(f"```python\n{solution}\n```\n")
            code_prompt_lines.append("請學習此解法（但不一定要完全照抄），並生成包含 main 區塊且能通過上述範例測試的完整程式碼。\n")
        # <<< 新增結束 >>>

        code_prompt_lines.append("⚠️ **重要**：請僅輸出一個 Python 程式碼區塊 ```python ... ```，絕對不要輸出任何額外文字或解釋。")

        code_prompt_string = "".join(code_prompt_lines)

        # 直接使用 call_ollama_cli，因為 build_code_prompt 有固定格式
        code_resp = call_ollama_cli(code_prompt_string)

    except Exception as e:
        print(f"     [錯誤] 'call_ollama_cli' (程式碼階段) 失敗: {e}")
        result["error"] = f"Code generation failed: {e}"
        return result

    # ---
    # === 階段 3: 提取程式碼 (同之前) ===
    # ---
    code = extract_code_block(code_resp)
    if not code:
        print("     [錯誤] 未能從模型回覆中提取程式碼。")
        result["error"] = "Failed to extract code from model response."
        result["validation_results"].append({
            "example_index": -1,
            "input": None,
            "expected_output": None,
            "success": False,
            "output": code_resp # 儲存原始回覆
        })
        return result

    result["generated_code"] = code

    # ---
    # === 階段 4: 驗證 (*** 邏輯修改：增加終端機輸出 ***) ===
    # ---
    all_examples_passed = True
    if not examples:
        print("     [提示] JSON 檔案未提供範例，無法進行輸入輸出驗證。僅檢查程式碼是否可執行。")
        try:
             # (MODIFICATION) 呼叫時 `expected_output=None`
             validation_result = validate_main_function(code, stdin_input="", expected_output=None)
             success, output_str = validation_result
             result["validation_results"].append({
                 "example_index": 0,
                 "input": "",
                 "expected_output": None,
                 "success": success,
                 "output": output_str # <--- 執行輸出在這裡
             })
             if success:
                 print("     [成功] 程式碼可執行 ✅")
                 if output_str:
                     print(f"       > 實際輸出: {repr(output_str)}")
                 result["success"] = True
             else:
                 print(f"     [失敗] 執行錯誤 ❌")
                 print(f"       > 實際輸出/錯誤: {repr(output_str)}")
                 result["error"] = "Code failed basic execution check."
                 all_examples_passed = False

        except Exception as e:
            print(f"     [嚴重錯誤] 'validate_main_function' 執行時發生例外: {e}")
            result["error"] = f"Validator crashed during basic execution check: {e}"
            # import traceback (已在上方導入)
            result["validation_results"].append({
                 "example_index": 0,
                 "input": "",
                 "expected_output": None,
                 "success": False,
                 "output": traceback.format_exc() # <--- 錯誤輸出
            })
            all_examples_passed = False
    else:
        print(f"     [階段 3] 正在驗證 {len(examples)} 個範例...")
        for i, ex in enumerate(examples):
            stdin_input = ex['input']
            expected_output = ex['output']
            print(f"       [範例 {i+1}/{len(examples)}] 輸入: {repr(stdin_input)}, 期望輸出: {repr(expected_output)}")

            try:
                # --- MODIFICATION START ---
                # 1. 呼叫 validator 時 `expected_output=None` 來獲取原始輸出
                validation_result = validate_main_function(code, stdin_input=stdin_input, expected_output=None)
                exec_success, raw_output_str = validation_result
                
                success = False # 預設為失敗
                output_to_store = raw_output_str # 儲存原始輸出（或錯誤訊息）

                if exec_success:
                    # 2. 如果執行成功，進行我們自己的「標準化比對」
                    norm_expected = _normalize_output(expected_output)
                    norm_actual = _normalize_output(raw_output_str)
                    
                    if norm_expected == norm_actual:
                        success = True
                    else:
                        # 3. 比對失敗，儲存詳細的錯誤訊息
                        output_to_store = (
                            f"[Output Mismatch (Normalized)]\n"
                            f"Expected (Norm): {repr(norm_expected)}\n"
                            f"Got (Norm):      {repr(norm_actual)}\n"
                            f"--- (Raw) ---\n"
                            f"Raw Expected: {repr(expected_output)}\n"
                            f"Raw Got:      {repr(raw_output_str)}"
                        )
                else:
                    # 1b. 如果執行失敗，success 保持 False，output_to_store 已是錯誤訊息
                    pass 
                
                # --- MODIFICATION END ---

                result["validation_results"].append({
                    "example_index": i,
                    "input": stdin_input,
                    "expected_output": expected_output,
                    "success": success, # <-- 使用我們計算出的 success
                    "output": output_to_store # <--- 儲存原始輸出或我們的錯誤訊息
                })

                if success:
                    print(f"       [成功] 範例 {i+1} 通過 ✅")
                else:
                    print(f"       [失敗] 範例 {i+1} 失敗 ❌")
                    # --- MODIFICATION: 打印更詳細的除錯資訊 ---
                    print(f"         > 期望 (Raw): {repr(expected_output)}")
                    print(f"         > 實際 (Raw): {repr(raw_output_str)}")
                    if exec_success: # 只有在執行成功但比對失敗時才打印
                        print(f"         > 期望 (Norm): {repr(_normalize_output(expected_output))}")
                        print(f"         > 實際 (Norm): {repr(_normalize_output(raw_output_str))}")
                    # --- MODIFICATION END ---
                    all_examples_passed = False

            except Exception as e:
                print(f"       [嚴重錯誤] 'validate_main_function' 對範例 {i+1} 執行時發生例外: {e}")
                result["error"] = f"Validator crashed on example {i+1}: {e}"
                # import traceback (已在上方導入)
                result["validation_results"].append({
                    "example_index": i,
                    "input": stdin_input,
                    "expected_output": expected_output,
                    "success": False,
                    "output": traceback.format_exc() # <--- 錯誤輸出
                })
                all_examples_passed = False

    if all_examples_passed:
        result["success"] = True
        print("     [總結] 所有範例驗證通過 ✅")
    else:
         result["success"] = False
         if examples:
             print("     [總結] 部分或全部範例驗證失敗 ❌")

    return result

if __name__ == "__main__":

    TOTAL_RUNS = 50
    print(f"--- 將開始執行 {TOTAL_RUNS} 次循環 ---")

    result_dir = script_dir / "result_pro"
    result_dir.mkdir(parents=True, exist_ok=True)
    print(f"輸出目錄: {result_dir}")

    overall_start_time = time.time()

    # *** 修改：從 1 開始循環 ***
    for run_index in range(41, TOTAL_RUNS + 1):
        print(f"\n=============================================")
        print(f"--- 開始第 {run_index} / {TOTAL_RUNS} 次循環 ---")
        print(f"=============================================")

        start_time = time.time()

        DATA_DIR = script_dir / "data"  
        # (整合) 定義兩個輸出檔案
        # *** 修改：為每個循環使用唯一的檔案名稱 ***
        FULL_RESULTS_FILE = result_dir / f"results_run_{run_index}.json"
        ERROR_SUMMARY_FILE = result_dir / f"summary_run_{run_index}.json"

        if not DATA_DIR.is_dir():
            print(f"[嚴重錯誤] 找不到 'data' 目錄於: {DATA_DIR}")
            print(f"--- 第 {run_index} 次循環失敗(Data Dir Not Found) ---")
            continue

        # --- (修復) 這現在是唯一的處理迴圈 ---
        print(f"--- 開始遍歷 {DATA_DIR} (使用包含範例驗證與 'lessons' 跳過邏輯) ---")

        all_results: List[Dict[str, Any]] = [] # 儲存 *所有問題* 的結果
        files_processed = 0
        files_skipped = 0 
        files_failed_load = 0 # 記錄 *完全無法載入* 的檔案數

        # *** 修改：直接遍歷 obj 目錄下的 JSON ***
        json_files = list(DATA_DIR.rglob("*.json"))
        # (您可以取消註解以下行來加入其他目錄)
        # json_files += list((script_dir / "obj1").rglob("*.json")) 
        # ...

        total_files = len(json_files)
        print(f"總共找到 {total_files} 個 .json 檔案。")

        for file_path in json_files:

            # --- DEBUG 修復：合併過濾邏輯 ---
            # (修復) 使用 DATA_DIR 作為相對路徑的基準
            relative_path = file_path.relative_to(DATA_DIR) 

            # 1. 跳過索引檔案 (來自第一個迴圈的邏輯)
            if file_path.name == "leetcode_index.json":
                files_skipped += 1
                continue
                
            # 2. 跳過 'lessons' 目錄 (來自第一個迴圈的邏輯)
            if relative_path.parts and relative_path.parts[0] == 'lessons':
                files_skipped += 1
                continue
            
            # 3. 跳過 README.md (來自第二個迴圈的邏輯)
            if file_path.name == "README.md":
                 files_skipped += 1
                 continue
            # --- 過濾邏輯結束 ---

            print(f"\n--- 正在處理檔案 ({files_processed + 1}/{total_files}): {relative_path} ---")

            # 3. (*** 重大修改 ***) 載入檔案中的 *所有* 題目
            all_problems_in_file = load_all_problems_from_file(file_path)

            if not all_problems_in_file:
                # 檔案讀取失敗，或檔案中沒有任何有效的題目
                files_failed_load += 1
                print(f"  [載入失敗] 無法從此檔案解析出任何有效的題目。")
                
                # 仍然為這個 *檔案* 記錄一筆失敗條目
                problem_result = {
                    "source_file": str(relative_path),
                    "problem_index_in_file": -1, # 特殊索引表示檔案載入失敗
                    "title": file_path.stem,
                    "generation_result": {
                        "success": False,
                        "error": "Could not parse any valid problems from this file."
                    }
                }
                all_results.append(problem_result)
                files_processed += 1 # 檔案已處理（雖然失敗了）
                continue # 繼續下一個 *檔案*

            # --- (*** 重大修改 ***) 迭代檔案中的 *每一道題目* ---
            print(f"  [載入成功] 於 {relative_path} 中找到 {len(all_problems_in_file)} 道題目。")

            for problem_index, (title, description, examples, solution) in enumerate(all_problems_in_file):
                
                print(f"    --- 處理題目 {problem_index + 1}/{len(all_problems_in_file)}: {title} ---")

                problem_result = {
                    "source_file": str(relative_path),
                    "problem_index_in_file": problem_index, # <-- 新增：記錄這是檔案中的第幾題
                    "title": title,
                    "description_snippet": description[:100] + "...",
                    "examples_loaded": len(examples),
                    "reference_solution_found": bool(solution),
                    "generation_result": None,
                }

                # 4. 為 *這道題目* 生成並驗證
                gen_result = generate_and_validate(description, examples, solution)
                problem_result["generation_result"] = gen_result

                # 5. 將 *這道題目* 的結果加入總列表
                all_results.append(problem_result)
            
            # 檔案處理完畢（無論包含多少題目）
            files_processed += 1
            # --- 題目迭代結束 ---

        # 6. 寫入 JSON 輸出 (完整報告 - 包含所有 *題目* 的結果)
        print("\n--- 處理完成 ---")
        try:
            with open(FULL_RESULTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
            print(f"\n[成功] 完整結果已儲存至: {FULL_RESULTS_FILE}")
        except Exception as e:
            print(f"\n[嚴重錯誤] 將完整結果寫入 JSON 失敗: {e}")

        # ---
        # === 7. (*** 重大修改 ***) 產生並寫入錯誤總結 (基於 *題目*) ===
        # ---

        success_count = 0
        failed_cases = [] # 儲存失敗的 *題目*

        # all_results 現在是 *題目* 的列表
        for item in all_results:
            gen_result = item.get("generation_result", {})
            
            # 檢查 "problem_index_in_file": -1 這種檔案層級的失敗
            if item.get("problem_index_in_file") == -1:
                 failed_cases.append({
                    "title": item.get("title", "N/A"),
                    "source_file": item.get("source_file", "N/A"),
                    "problem_index_in_file": -1,
                    "generation_error": gen_result.get("error"), # 檔案載入錯誤
                    "failed_validation_details": [],
                    "generated_code": None,
                    "virtual_code": None,
                 })
                 continue # 繼續下一個條目

            # 正常的題目層級檢查
            if gen_result.get("success") is True:
                success_count += 1
            else:
                # 提取更詳細的失敗資訊
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
                    "problem_index_in_file": item.get("problem_index_in_file"), # <-- 包含題目索引
                    "generation_error": gen_result.get("error"), # 生成階段錯誤
                    "failed_validation_details": failed_example_details, # 驗證階段錯誤
                    "generated_code": gen_result.get("generated_code"), # 失敗的程式碼
                    "virtual_code": gen_result.get("virtual_code"), # 失敗的虛擬碼
                })

        # (*** 修改 ***) 總嘗試次數 = all_results 的長度
        num_attempted_gen = len(all_results) 
        # 失敗計數 = failed_cases 的長度
        num_failed_gen = len(failed_cases)
        # 成功計數 (已計算)
        # num_success_gen = success_count
        
        # (*** 驗證 ***)
        # num_attempted_gen 應該等於 num_failed_gen + success_count
        if num_attempted_gen != (num_failed_gen + success_count):
             print(f"[警告] 總結計數不匹配！Attempted: {num_attempted_gen}, Failed: {num_failed_gen}, Success: {success_count}")


        error_summary = {
            "run_index": run_index,
            "total_files_found": total_files,
            "total_files_processed": files_processed, # 處理的 *檔案* 數
            "files_skipped": files_skipped, # 跳過的 *檔案* 數
            "files_failed_load": files_failed_load, # 完全無法載入的 *檔案* 數
            "---": "--- (以下基於 *題目* 總數) ---",
            "total_problems_attempted": num_attempted_gen, # 處理的 *題目* 總數
            "generation_and_validation_success_count": success_count, # 成功的 *題目* 數
            "generation_or_validation_failure_count": num_failed_gen, # 失敗的 *題目* 數
            "failed_cases_details": failed_cases # 失敗 *題目* 的詳情
        }

        try:
            with open(ERROR_SUMMARY_FILE, 'w', encoding='utf-8') as f:
                json.dump(error_summary, f, indent=2, ensure_ascii=False)
            print(f"[成功] 錯誤總結已儲存至: {ERROR_SUMMARY_FILE}")
        except Exception as e:
            print(f"[嚴重錯誤] 將錯誤總結寫入 JSON 失敗: {e}")

        # 8. 輸出總結
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
