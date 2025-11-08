import re
import json
import sys
import random
import traceback
from typing import List, Dict, Any, Optional
from core.model_interface import call_ollama_cli, build_virtual_code_prompt, generate_response, build_cot_test_prompt, build_mutation_killing_prompt, build_ga_crossover_prompt, build_ga_mutation_prompt
from core.validators import validate_main_function, _normalize_output
from core.code_extract import extract_code_block, extract_json_block
# 確保 MutationRunner 已正確定義在 core.mutation_runner 並可被 import
from core.mutation_runner import MutationRunner

def json_to_unittest(json_tests: list) -> str:
    """
    將 JSON 測資 ([[input, output], ...]) 轉換為 MutPy 可執行的 unittest 程式碼字串。
    """
    code_lines = [
        "import unittest",
        "from unittest.mock import patch",
        "from io import StringIO",
        "import sys",
        "",
        "class TestSolution(unittest.TestCase):"
    ]

    for i, test in enumerate(json_tests):
        if not isinstance(test, list) or len(test) < 2:
            continue
            
        # 確保輸入輸出為字串，並處理脫逸字元以放入 f-string
        inp = str(test[0]).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
        exp = str(test[1]).replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"')
        
        test_method = f"""
    def test_case_{i+1}(self):
        user_input = '{inp}'
        expected_output = '{exp}'
        with patch('sys.stdout', new=StringIO()) as fake_out:
            # 模擬 stdin 輸入
            with patch('builtins.input', side_effect=user_input.split('\\n') if user_input else []):
                try:
                    if 'main' in globals():
                        main()
                except StopIteration: 
                    pass # 忽略因 input 不足導致的錯誤
                except SystemExit:
                    pass # 忽略 exit()
                    
        # 比對標準化後的輸出 (去除前後空白)
        self.assertEqual(fake_out.getvalue().strip(), expected_output.strip())
"""
        code_lines.append(test_method)

    return "\n".join(code_lines)

def generate_tests(user_need: str, code: str, mode: str = "B") -> list[tuple]:
    """
    自動生成測資，回傳格式: [(func_name, [args], expected), ...]
    mode="B": 使用改進的 CoT Prompt 快速生成 (arXiv:2504.20357)。
    mode="MuTAP": 進階模式，使用變異測試循環 (arXiv:2308.16557)。
    mode="GA": 遺傳演算法模式，透過 LLM 進行測資的交配與突變 (arXiv:2504.20357)。
    """
    func_name = None
    for line in code.splitlines():
        if line.strip().startswith("def "):
            func_name = line.split()[1].split("(")[0]
            break
    if not func_name:
        func_name = "solution"

    tests = []
    print(f"[generate_tests] 正在以模式 '{mode}' 生成測資...")

    # --- 階段 1: 初始生成 (種群初始化) ---
    prompt = build_cot_test_prompt(user_need)
    resp = generate_response(prompt)
    extracted_json = extract_json_block(resp)
    
    # (簡單的 fallback 機制)
    if not extracted_json:
         m = re.findall(r"\[\s*\[.*?\]\s*\]", resp, re.DOTALL)
         if m:
             try: extracted_json = json.loads(m[0])
             except: pass

    if extracted_json:
        for t in extracted_json:
            if isinstance(t, list) and len(t) >= 2:
                tests.append((func_name, [t[0]], t[1]))
    
    print(f"[generate_tests] 初始種群大小: {len(tests)}")

    # --- 階段 2a: GA 演化循環 (僅在 GA 模式執行) ---
    if mode.upper() == "GA" and len(tests) >= 2:
        print("\n[GA] 進入遺傳演算法演化循環...")
        GENERATIONS = 2   # 演化代數
        OFFSPRING_PER_GEN = 3 # 每代產生子代數

        current_population = [[t[1][0], t[2]] for t in tests] # 取出 [input, output]

        for gen in range(GENERATIONS):
            print(f"  > [GA] 第 {gen+1}/{GENERATIONS} 代演化中...")
            new_offspring = []
            
            for _ in range(OFFSPRING_PER_GEN):
                # --- 運算子 1: 交配 (Crossover) ---
                if random.random() > 0.3: # 70% 機率交配
                    parents = random.sample(current_population, 2)
                    ga_prompt = build_ga_crossover_prompt(user_need, parents[0], parents[1])
                    op_type = "交配"
                # --- 運算子 2: 突變 (Mutation) ---
                else: # 30% 機率突變
                    parent = random.choice(current_population)
                    ga_prompt = build_ga_mutation_prompt(user_need, parent)
                    op_type = "突變"

                # 呼叫 LLM 執行演化操作
                ga_resp = generate_response(ga_prompt)
                child_json = extract_json_block(ga_resp) # 預期回傳 [input, output]

                if child_json and isinstance(child_json, list) and len(child_json) >= 2:
                     # 簡單的去重檢查 (檢查 input 是否已存在)
                     if not any(existing[0] == child_json[0] for existing in current_population):
                         new_offspring.append(child_json)
                         print(f"    [GA] ({op_type}) 產生新個體: Input={child_json[0]}")

            # 將新子代加入種群
            current_population.extend(new_offspring)
        
        # 將最終種群轉換回系統所需格式
        tests = [(func_name, [p[0]], p[1]) for p in current_population]
        print(f"[GA] 演化完成，最終種群大小: {len(tests)}")

    # --- 階段 2: MuTAP 增強循環 (僅在 MuTAP 模式且有程式碼時執行) ---
    if mode.upper() == "MUTAP" and code.strip() and tests:
        print("\n[MuTAP] 進入變異測試增強循環 (arXiv:2308.16557)...")
        
        # 1. 準備數據：還原回 [[input, output]] 格式以便轉換
        current_json_tests = [[t[1][0], t[2]] for t in tests]
        
        # 2. 轉換為 unittest 代碼
        unittest_code = json_to_unittest(current_json_tests)
        
        # 3. 執行變異分析
        # 注意：請確保您的環境已安裝 mutpy (pip install mutpy)
        runner = MutationRunner(target_code=code, test_code=unittest_code)
        survivors = runner.find_surviving_mutants()

        if survivors is None:
             print("[MuTAP] 變異測試執行失敗 (可能缺少 mutpy 套件或路徑錯誤)。")
        elif not survivors:
             print("[MuTAP] 完美！目前的測資已非常強健，沒有發現存活的變異體。")
        else:
             print(f"[MuTAP] 發現 {len(survivors)} 個存活的變異體 (潛在測試盲點)！")
             
             # 4. 針對存活變異體生成殺手測資 (Iterative Feedback)
             # 為了效能，我們限制只處理前 3 個變異體
             for i, mutant in enumerate(survivors[:3]):
                 print(f"  > [MuTAP] 正在分析第 {i+1} 個變異體並生成殺手測資...")
                 
                 # 建構殺手提示詞，傳入當前測資與變異體資訊
                 kill_prompt = build_mutation_killing_prompt(code, json.dumps(current_json_tests, ensure_ascii=False), mutant)
                 kill_resp = generate_response(kill_prompt)
                 new_tests_json = extract_json_block(kill_resp)

                 if new_tests_json:
                     print(f"    [MuTAP] 成功生成 {len(new_tests_json)} 組新測資！")
                     for nt in new_tests_json:
                         if isinstance(nt, list) and len(nt) >= 2:
                             # 加入總測資列表
                             tests.append((func_name, [nt[0]], nt[1]))
                             # 同步更新用於下一輪分析的暫存列表 (雖然此處只跑一輪)
                             current_json_tests.append([nt[0], nt[1]])
                 else:
                     print("    [MuTAP] 模型未能為此變異體生成有效的殺手測資。")
             
             print(f"[MuTAP] 增強完成，最終測資數量: {len(tests)}")

    return tests

def generate_and_validate(user_need: str, examples: List[Dict[str, str]], solution: Optional[str]) -> Dict[str, Any]:
    """
    (從 testrun.py 移入)
    1. Need -> 虛擬碼
    2. 虛擬碼 + Examples + Solution -> 程式碼
    3. 驗證 (M 模式，使用 JSON 中的 examples)
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
    # === 階段 1: 生成虛擬碼 ===
    # ---
    try:
        print("     [階段 1] 正在生成虛擬碼...")
        vc_prompt = build_virtual_code_prompt(user_need) #
        vc_resp = call_ollama_cli(vc_prompt) #
        virtual_code = vc_resp 
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

        # *** 動態構建包含 solution 的提示 (邏輯同 testrun.py) ***
        code_prompt_lines = [
            "用繁體中文回答。\n你是程式碼生成助理。\n任務：依據使用者需求、虛擬碼、範例，並參考提供的解法，產生正確可執行的 Python 程式碼，並加上白話註解。\n",
            f"原始需求：\n{user_need}\n",
            f"虛擬碼：\n{virtual_code}\n", 
            "生成的程式碼必須包含一個 `if __name__ == \"__main__\":` 區塊。\n",
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

        if solution:
            code_prompt_lines.append("您可以參考以下的參考解法：\n")
            code_prompt_lines.append(f"```python\n{solution}\n```\n")
            code_prompt_lines.append("請學習此解法（但不一定要完全照抄），並生成包含 main 區塊且能通過上述範例測試的完整程式碼。\n")

        code_prompt_lines.append("⚠️ **重要**：請僅輸出一個 Python 程式碼區塊 ```python ... ```，絕對不要輸出任何額外文字或解釋。")

        code_prompt_string = "".join(code_prompt_lines)

        code_resp = call_ollama_cli(code_prompt_string) #

    except Exception as e:
        print(f"     [錯誤] 'call_ollama_cli' (程式碼階段) 失敗: {e}")
        result["error"] = f"Code generation failed: {e}"
        return result

    # ---
    # === 階段 3: 提取程式碼 ===
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
    # === 階段 4: 驗證 ===
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
            result["validation_results"].append({
                 "example_index": 0,
                 "input": "",
                 "expected_output": None,
                 "success": False,
                 "output": traceback.format_exc()
            })
            all_examples_passed = False
    else:
        print(f"     [階段 3] 正在驗證 {len(examples)} 個範例...")
        for i, ex in enumerate(examples):
            stdin_input = ex['input']
            expected_output = ex['output']
            print(f"       [範例 {i+1}/{len(examples)}] 輸入: {repr(stdin_input)}, 期望輸出: {repr(expected_output)}")

            try:
                # 1. 呼叫 validator (不自動比對)
                validation_result = validate_main_function(code, stdin_input=stdin_input, expected_output=None) #
                exec_success, raw_output_str = validation_result
                
                success = False
                output_to_store = raw_output_str 

                if exec_success:
                    # 2. 執行成功，進行「標準化比對」
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
        result["success"] = True
        print("     [總結] 所有範例驗證通過 ✅")
    else:
         result["success"] = False
         if examples:
             print("     [總結] 部分或全部範例驗證失敗 ❌")

    return result

def generate_tests_with_oracle(user_need: str, reference_code: str, num_tests: int = 5) -> list:
    """
    [高準確率模式] 利用參考解法 (Oracle) 自動計算預期輸出。
    1. 要求 LLM 僅生成具備高覆蓋率的「輸入 (stdin)」。
    2. 執行 reference_code 以獲取絕對正確的「輸出 (stdout)」。
    """
    sys_prompt = (
        "你是一位專業的測試工程師。請分析以下程式需求，生成一組具備高覆蓋率的「純輸入」資料。\n"
        "請專注於設計各種邊界情況 (Edge Cases) 與極端輸入，以確保程式的穩健性。\n"
        f"需求描述:\n{user_need}\n\n"
        "請直接輸出一個 JSON 格式的字串陣列 (List of Strings)，每一項代表一次完整的標準輸入 (stdin) 內容。\n"
        "不需要任何解釋或其他文字。\n"
        "格式範例: [\"輸入1第一行\\n輸入1第二行\", \"輸入2僅一行\", \"1 2 3\\n4 5 6\"]\n"
    )
    
    print("     [Oracle] 正在生成高覆蓋率輸入...")
    resp = generate_response(sys_prompt)
    inputs = extract_json_block(resp)

    if not inputs or not isinstance(inputs, list):
        print(f"     [Oracle 警告] 無法從模型回覆中提取輸入列表。")
        return []

    valid_tests = []
    print(f"     [Oracle] 正在透過參考解法計算 {len(inputs)} 組標準答案...")

    for i, inp in enumerate(inputs):
        stdin_input = str(inp)
        # 執行參考解法來獲取標準輸出
        # 注意：這要求 reference_code 必須是完整的可執行腳本 (包含讀取 stdin 的部分)
        success, oracle_output = validate_main_function(reference_code, stdin_input, expected_output=None)

        if success:
            # 成功獲得 Oracle 輸出，這組測資是可信的
            valid_tests.append([stdin_input, oracle_output.strip()])
        else:
             print(f"     [Oracle 失敗] 參考解法無法處理第 {i+1} 組輸入，已略過。")

    return valid_tests[:num_tests]