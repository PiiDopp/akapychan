

from core import ask_input, generate_response, \
                 extract_code_block, extract_json_block, parse_tests_from_text, normalize_tests, \
                 validate_python_code, generate_tests, validate_main_function
from core.model_interface import build_virtual_code_prompt, build_test_prompt, build_explain_prompt, build_code_prompt, call_ollama_cli, MODEL_NAME, interactive_chat, interactive_langchain_chat, interactive_code_modification_loop, build_stdin_code_prompt, build_fix_code_prompt, interactive_translate, get_code_suggestions, build_mutation_killing_prompt
from quiz.quiz_mode import quiz_mode
from core.explain_user_code import explain_user_code
from core.explain_error import explain_code_error
from core.mutation_runner import MutationRunner
from core.test_utils import json_to_unittest


def interactive_session():
    print("=== Python Code Generator (Ollama + CodeLlama, Local Only) ===")
    while True:
        mode = ask_input("請選擇模式 (1: 生成程式碼, 2: 出題, 3: 使用者程式碼驗證, 4: 程式碼解釋, 5:翻譯, 6:提示, q 離開)", "1")
        if mode.lower() in ("q", "quit", "exit"):
            break
 # ========== 模式 1: 生成程式碼 ==========
        elif mode == "1":
            print("請輸入需求說明，多行輸入，結束請輸入單獨一行 'END'。")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                lines.append(line)

            user_need = "\n".join(lines).strip()
            if not user_need:
                print("[提示] 沒有輸入需求，取消操作。")
                continue

            # ========== 先生成虛擬碼 ==========
            virtual_code = "" 
            while True:
                vc_prompt = build_virtual_code_prompt(user_need)
                vc_resp = generate_response(vc_prompt)
                print("\n=== 模型回覆 (虛擬碼) ===\n")
                print(vc_resp, "\n")

                confirm = input("是否符合需求？(y: 繼續, n: 重新生成, a: 新增補充說明) [y]：").strip().lower()
                if confirm in ("", "y", "yes"):
                    virtual_code = vc_resp
                    break
                elif confirm in ("n", "no"):
                    print("[提示] 重新生成虛擬碼...\n")
                    continue
                elif confirm == "a":
                    print("請輸入補充說明，多行輸入，結束請輸入單獨一行 'END'。")
                    extra_lines = []
                    while True:
                        try:
                            line = input()
                        except EOFError:
                            break
                        if line.strip() == "END":
                            break
                        extra_lines.append(line)
                    extra_info = "\n".join(extra_lines).strip()
                    if extra_info:
                        user_need += "\n(補充說明: " + extra_info + ")"
                    print("[提示] 已加入補充說明，重新生成虛擬碼...\n")
                    continue
                else:
                    print("[提示] 無效輸入，請輸入 y/n/a。")

            # ========== (新) 第一步：先產生測資 ==========
            print("\n[提示] 正在生成測資...\n")
            test_prompt = build_test_prompt(user_need)
            test_resp = generate_response(test_prompt)
            print("\n=== 模型回覆 (測資) ===\n")
            print(test_resp, "\n")

            json_tests = extract_json_block(test_resp) or parse_tests_from_text(user_need)

            if json_tests:
                print(f"[提示] 已成功提取 {len(json_tests)} 筆測資。")
            else:
                print("[警告] 未能從模型回覆中提取 JSON 測資。")

            # ========== (新) 第二步：依照虛擬碼和測資產生程式碼 ==========
            print("\n[提示] 正在根據虛擬碼和測資生成 (stdin/stdout) 程式碼...") # 
            
            code_prompt_string = build_stdin_code_prompt(
                user_need, 
                virtual_code, 
                ai_generated_tests=json_tests 
            )
            code_resp = generate_response(code_prompt_string) 

            print("\n=== 模型回覆 (程式碼，stdin/stdout 版本) ===\n") # 
            print(code_resp, "\n")

            code_or_list = extract_code_block(code_resp)
            if isinstance(code_or_list, list) and code_or_list:
                code = code_or_list[0] 
            elif isinstance(code_or_list, str):
                code = code_or_list
            else:
                code = None 

            # 第三步：產生解釋
            if code:
                explain_prompt = build_explain_prompt(user_need, code)
                explain_resp = generate_response(explain_prompt)
                print("\n=== 模型回覆 (解釋) ===\n")
                print(explain_resp, "\n")
                
                verify = ask_input("要執行程式 (包含 main 中的測試) 嗎? (M:執行測試, N: 不驗證)", "M")

                if verify.upper() == "M":
                    print("\n[驗證中] 正在使用 AI 生成的測資逐一驗證...")
                    if not json_tests:
                        print("[警告] 找不到 AI 生成的 JSON 測資。僅執行一次 (無輸入)...")
                        success, output_msg = validate_main_function(code, stdin_input=None, expected_output=None)
                        print(f"執行結果 (無輸入): {'成功' if success else '失敗'}\n{output_msg}")
                    else:
                        all_passed = True
                        for i, test in enumerate(json_tests):
                            print(f"\n--- 測試案例 {i+1} ---")
                            
                            if not (isinstance(test, list) and len(test) == 2):
                                print(f"  [警告] 測資格式不符 (應為 [input, output]): {repr(test)}")
                                print(f"  結果: [跳過]")
                                all_passed = False 
                                continue 
                            
                            test_input_val = test[0] 
                            test_output_val = test[1]
                            
                            print(f"  Input: {repr(test_input_val)}")
                            print(f"  Expected Output: {repr(test_output_val)}")

                            test_input_str = str(test_input_val) if test_input_val is not None else None
                            test_output_str = str(test_output_val) if test_output_val is not None else None

                            success, output_msg = validate_main_function(
                                code=code,
                                stdin_input=test_input_str,
                                expected_output=test_output_str
                            )
                            print(f"  詳細資訊/執行結果:\n{output_msg}")
                            if success:
                                print(f"  結果: [通過]")
                            else:
                                print(f"  結果: [失敗]")
                                print(f"  詳細資訊:\n{output_msg}")
                                all_passed = False
                        
                        print("\n" + "="*20)
                        if all_passed:
                            print("總結: [成功] 所有測資均已通過。")
                        else:
                            print("總結: [失敗] 部分測資未通過。")
                else:
                    validate_python_code(code, [], user_need)

                # ========== 整合點：詢問是否進入修改模式 ==========
                print("\n" + "="*20)
                print("程式碼已生成。")
                modify = ask_input("是否要進入互動式修改模式？(y/n)", "n")
                
                if modify.lower() in ("y", "yes"):
                    print("\n=== 進入互動式修改模式 ===\n")
                    
                    current_code = code 
                    history = [f"初始需求: {user_need}"]

                    while True:
                        print("\n" + "="*40)
                        print("請輸入您的下一步操作：")
                        print("  - [修改/優化/重構]：輸入您的需求說明")
                        print("  - [驗證]：輸入 'VERIFY' 或 'V'") 
                        print("  - [解釋]：輸入 'EXPLAIN' 或 'E'")
                        print("  - [完成]：輸入 'QUIT' (返回主選單)")
                        print("="*40)

                        user_input = input("您的操作 (或修改需求): ").strip()

                        if user_input.upper() == "QUIT":
                            print("\n開發模式結束。最終程式碼如下：")
                            print(f"```python\n{current_code}\n```")
                            print("[提示] 返回主選單。")
                            break 

                        if user_input.upper() in ("VERIFY", "V"):
                            print("\n[驗證中] 正在使用 AI 生成的測資逐一驗證 (當前程式碼)...")
                            if not json_tests:
                                print("[警告] 找不到 AI 生成的 JSON 測資。僅執行一次 (無輸入)...")
                                success, output_msg = validate_main_function(current_code, stdin_input=None, expected_output=None)
                                print(f"執行結果 (無輸入): {'成功' if success else '失敗'}\n{output_msg}")
                                if not success:
                                    print("\n[提示] 驗證失敗。您可能需要 '解釋' 錯誤或提供 '修改' 需求。")
                                else:
                                    print("\n[提示] 程式執行成功。")
                            else:
                                all_passed = True
                                for i, test in enumerate(json_tests):
                                    print(f"\n--- 測試案例 {i+1} (驗證當前程式碼) ---")

                                    if not (isinstance(test, list) and len(test) == 2):
                                        print(f"  [警告] 測資格式不符 (應為 [input, output]): {repr(test)}")
                                        print(f"  結果: [跳過]")
                                        all_passed = False 
                                        continue 
                                    
                                    test_input_val = test[0]
                                    test_output_val = test[1]

                                    print(f"  Input: {repr(test_input_val)}")
                                    print(f"  Expected Output: {repr(test_output_val)}")
                                    
                                    # 強制將 input 和 output 轉為 string
                                    test_input_str = str(test_input_val) if test_input_val is not None else None
                                    test_output_str = str(test_output_val) if test_output_val is not None else None
                                    
                                    success, output_msg = validate_main_function(
                                        code=current_code, 
                                        stdin_input=test_input_str,
                                        expected_output=test_output_str
                                    )
                                    print(f"  詳細資訊/執行結果:\n{output_msg}")
                                    if success:
                                        print(f"  結果: [通過]")
                                    else:
                                        print(f"  結果: [失敗]")
                                        print(f"  詳細資訊:\n{output_msg}")
                                        all_passed = False
                                
                                print("\n" + "="*20)
                                if all_passed:
                                    print("總結: [成功] 所有測資均已通過。")
                                else:
                                    print("總結: [失敗] 部分測資未通過。")
                                    print("\n[提示] 驗證失敗。您可能需要 '解釋' 錯誤或提供 '修改' 需求。")

                        elif user_input.upper() in ("EXPLAIN", "E"):
                            print("\n[解釋中] 產生程式碼解釋...")
                            explain_prompt = build_explain_prompt(user_need, current_code)
                            explain_resp = generate_response(explain_prompt)
                            print("\n=== 程式碼解釋 ===\n")
                            print(explain_resp)

                        else: 
                            modification_request = user_input
                            print(f"\n[修正中] 正在根據您的要求 '{modification_request}' 修正程式碼...")

                            fix_prompt_string = build_fix_code_prompt(
                                user_need, 
                                virtual_code, 
                                ai_generated_tests=json_tests,
                                history=history, 
                                current_code=current_code, 
                                modification_request=modification_request
                            )
                            
                            fix_resp = generate_response(fix_prompt_string)

                            new_code_or_list = extract_code_block(fix_resp)
                            if isinstance(new_code_or_list, list) and new_code_or_list:
                                new_code = new_code_or_list[0]
                            elif isinstance(new_code_or_list, str):
                                new_code = new_code_or_list
                            else:
                                new_code = None

                            if new_code:
                                current_code = new_code
                                history.append(f"修改: {modification_request}")
                                print("\n=== 程式碼 (新版本) ===\n")
                                print(f"```python\n{current_code}\n```")
                            else:
                                print("[警告] 模型無法生成修正後的程式碼。請重試或輸入更明確的指令。")
                else:
                    print("[提示] 略過修改，返回主選單。")
            else:
                print("[提示] 沒有找到 Python 程式碼區塊。")

        elif mode == "2":
            quiz_mode()
        elif mode == "3":
            print("\n請貼上您要驗證的 Python 完整程式碼 (需包含讀取 stdin 的部分)：")
            print("結束輸入請輸入單獨一行 'END'。")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                lines.append(line)
            user_code = "\n".join(lines)
            if not user_code.strip():
                print("[提示] 未輸入程式碼，返回主選單。")
                continue

            print("\n請輸入這段程式碼的「需求說明」(AI 將據此生成測資)：")
            print("多行輸入，結束請輸入單獨一行 'END'。")
            need_lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "END":
                    break
                need_lines.append(line)
            user_need = "\n".join(need_lines).strip()
            if not user_need:
                 print("[提示] 未輸入需求，僅執行一次程式碼 (無輸入)。")
                 success, msg = validate_main_function(user_code, None, None)
                 print("\n=== 執行結果 ===\n" + msg)
                 continue

            # --- 選擇測資生成策略 ---
            print("\n請選擇測資生成策略：")
            print("  [1] 標準模式 (Standard CoT) - 快速生成基礎測資")
            print("  [2] 遺傳演算法 (GA) - 透過交配與突變產生多樣化測資 (較慢)")
            print("  [3] 變異測試 (MuTAP) - 找出程式盲點並生成殺手測資 (最慢，需安裝 mutpy)")
            strategy = ask_input("您的選擇 [1]: ", "1")
            
            mode_map = {"1": "B", "2": "GA", "3": "MUTAP"}
            selected_mode = mode_map.get(strategy, "B")

            # 呼叫核心函式生成測資
            # generate_tests 回傳格式為 [(func_name, [input_args], expected_output), ...]
            raw_tests = generate_tests(user_need, user_code, mode=selected_mode)

            if not raw_tests:
                print("[警告] 未能生成任何有效測資。")
                continue

            # --- 執行驗證迴圈 ---
            print(f"\n=== 開始驗證 (共 {len(raw_tests)} 筆測資) ===")
            all_passed = True
            pass_count = 0

            for i, test_tuple in enumerate(raw_tests):
                # test_tuple 格式: (func_name, [input_arg], expected_output)
                # 我們這裡假設 input_arg 的第一個元素就是完整的 stdin 輸入字串
                try:
                    inp_arg = test_tuple[1][0] if test_tuple[1] else ""
                    expected = test_tuple[2]
                    
                    print(f"\n--- 測試案例 {i+1} ---")
                    print(f"輸入 (stdin): {repr(inp_arg)}")
                    print(f"預期輸出: {repr(expected)}")

                    success, output_msg = validate_main_function(user_code, str(inp_arg), str(expected))
                    
                    if success:
                        print("結果: [通過] ✅")
                        pass_count += 1
                    else:
                        print("結果: [失敗] ❌")
                        print(f"實際輸出/錯誤訊息:\n{output_msg.strip()}")
                        all_passed = False
                except IndexError:
                    print(f"[跳過] 測試案例 {i+1} 格式異常。")
                    all_passed = False

            print("\n" + "="*30)
            print(f"驗證完成！ 通過率: {pass_count}/{len(raw_tests)}")
            if all_passed:
                print("🎉 恭喜！您的程式碼通過了所有測試案例。")
                if selected_mode in ("GA", "MUTAP"):
                    print("(在高強度測試模式下全數通過，代表您的程式碼相當穩健！)")
            else:
                print("⚠️ 存在失敗的測試案例，請參考上方詳細資訊進行除錯。")
                    # ... (原有的錯誤解釋邏輯)

        elif mode == "4":
            explain_user_code()
        elif mode == "5":
            interactive_translate()
        elif mode == "6":
            get_code_suggestions()
        else:
            interactive_chat()


if __name__ == "__main__":
    try:
        interactive_session()
    except KeyboardInterrupt:
        print("\n使用者中斷，結束。")