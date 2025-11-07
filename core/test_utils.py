import re
import json
import traceback
import random
import sys
import io
import trace
from typing import List, Dict, Any, Optional, Tuple
from core.model_interface import call_ollama_cli, build_virtual_code_prompt, build_initial_population_prompt, build_crossover_prompt, build_mutation_prompt
from core.validators import validate_main_function, _normalize_output
from core.code_extract import extract_code_block, extract_json_block
from core.model_interface import generate_response

# === 新增：適應度評估函式 ===
def calculate_fitness(code: str, test_input: str, expected_output: str) -> float:
    """
    計算測資的適應度 (Fitness)。
    這裡使用「程式碼行覆蓋數」作為簡單的代理指標。
    覆蓋越多行，分數越高；若執行失敗，分數極低。
    """
    # 1. 準備執行環境
    # 將使用者程式碼包裝成一個可被 trace 的函式
    wrapped_code = f"""
import sys
def target_func():
    # 模擬 stdin
    sys.stdin = io.StringIO({repr(test_input)})
    try:
        # --- 使用者程式碼 ---
{code}
        # -------------------
    except Exception:
        pass # 捕捉執行期錯誤以免中斷 trace
"""
    
    # 2. 使用 trace 模組執行並計算覆蓋行數
    tracer = trace.Trace(count=1, trace=0)
    try:
        # 建立一個乾淨的 namespace 來執行
        namespace = {"io": io, "sys": sys}
        # 先編譯包裝後的代碼
        exec(wrapped_code, namespace)
        
        # 開始追蹤執行
        tracer.runfunc(namespace['target_func'])
        
        # 3. 計算適應度
        # 簡單邏輯：執行的行數越多，代表觸及的邏輯越多 (這是一個簡化的假設)
        # 論文建議使用更嚴謹的 Branch Coverage，但這需要複雜的插樁(instrumentation)
        counts = tracer.results().counts
        covered_lines = len(counts)
        
        # 基本分：能成功執行就有 1 分
        fitness = 1.0 + (covered_lines * 0.1)

        # 額外加分：如果實際輸出與預期輸出相符 (雖然我們是在生成測資，但這能確保測資品質)
        # 這裡需要真正執行一次來獲取輸出，稍微耗時但較準確
        # success, actual_output = validate_main_function(code, test_input, expected_output)
        # if success:
        #      fitness += 5.0 # 大幅獎勵正確的測資

        return fitness

    except Exception as e:
        # print(f"[Fitness Debug] Error: {e}")
        return 0.1 # 執行失敗，給予極低分

# === 重寫：基於 GA 的測試生成 ===
def generate_tests_ga(user_need: str, code: str, generations=3, pop_size=6) -> List[List[str]]:
    """
    使用遺傳演算法 (GA) 生成高品質測資。
    流程：初始化 -> 評估 -> 選擇 -> 交配/突變 -> 迴圈
    """
    print(f"\n[GA] 啟動演化式測試生成 (Generations={generations}, Pop={pop_size})...")
    
    # 1. 初始化族群 (Initial Population)
    init_prompt = build_initial_population_prompt(user_need, n=pop_size)
    init_resp = generate_response(init_prompt)
    population = extract_json_block(init_resp)
    
    if not population:
        print("[GA] 初始化失敗，回退到基本模式。")
        return []
        
    # 確保族群格式正確 [[inp, out], ...]
    population = [p for p in population if isinstance(p, list) and len(p) >= 2]

    for gen in range(generations):
        print(f"  [GA] Generation {gen+1}/{generations}...")
        
        # 2. 評估適應度 (Evaluation)
        scored_pop = []
        for individual in population:
            inp, outp = str(individual[0]), str(individual[1])
            fitness = calculate_fitness(code, inp, outp)
            scored_pop.append((individual, fitness))
        
        # 依適應度排序 (高的在前)
        scored_pop.sort(key=lambda x: x[1], reverse=True)
        print(f"    > Best Fitness: {scored_pop[0][1]:.2f} (Input: {scored_pop[0][0][0]!r})")

        # 3. 選擇 (Selection) - 保留前 50% 精英
        elite_count = max(2, int(pop_size * 0.5))
        elites = [x[0] for x in scored_pop[:elite_count]]
        next_gen = elites[:]
        
        # 4. 繁殖 (Reproduction: Crossover & Mutation)
        while len(next_gen) < pop_size:
            if random.random() < 0.6 and len(elites) >= 2: # 60% 機率交配
                parents = random.sample(elites, 2)
                prompt = build_crossover_prompt(user_need, parents[0], parents[1])
                # 呼叫模型進行「智慧交配」
                resp = call_ollama_cli(prompt) 
                child = extract_json_block(resp)
                if child and isinstance(child, list): # 可能是單一測資 [inp, out]
                     # 有時模型會回傳多個，需處理
                     if len(child) > 0 and isinstance(child[0], list): 
                         next_gen.extend(child[:1]) # 取第一個
                     else:
                         next_gen.append(child)
            else: # 40% 機率突變
                parent = random.choice(elites)
                prompt = build_mutation_prompt(user_need, parent)
                resp = call_ollama_cli(prompt)
                mutant = extract_json_block(resp)
                if mutant and isinstance(mutant, list):
                     if len(mutant) > 0 and isinstance(mutant[0], list):
                         next_gen.extend(mutant[:1])
                     else:
                         next_gen.append(mutant)
        
        # 更新族群
        population = next_gen[:pop_size] # 確保不超過大小

    # 演化結束，返回最終族群
    print(f"[GA] 演化完成。")
    return population

# === 修改原有的 generate_tests 以支援新模式 ===
def generate_tests(user_need: str, code: str = None, mode: str = "GA") -> List[Any]:
    """
    自動生成測資。
    mode="GA": 使用遺傳演算法 (推薦，品質較高但較慢)。
    mode="B" (Basic): 舊版單次生成。
    """
    if mode == "GA" and code:
        # 如果有程式碼，就用 GA 針對該程式碼演化測資
        return generate_tests_ga(user_need, code)
    
    # --- 舊版邏輯 (Basic) ---
    # (保留您原本的 B 模式作為備用)
    sys_prompt = (
        "用繁體中文回答。\n"
        "請根據以下需求，生成 3~5 組測資，格式為 JSON 陣列：\n"
        f"需求: {user_need}\n"
        "格式範例: [[輸入, 輸出], ...]\n"
    )
    resp = generate_response(sys_prompt)
    json_tests = extract_json_block(resp)
    return json_tests if json_tests else []


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