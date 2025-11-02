

from core import ask_input, generate_response, \
                 extract_code_block, extract_json_block, parse_tests_from_text, normalize_tests, \
                 validate_python_code, generate_tests, validate_main_function
from core.model_interface import build_virtual_code_prompt, build_test_prompt, build_explain_prompt, build_code_prompt, call_ollama_cli, MODEL_NAME, interactive_chat, interactive_langchain_chat, interactive_code_modification_loop, build_stdin_code_prompt, build_fix_code_prompt
from quiz.quiz_mode import quiz_mode
from verify_user_code import verify_user_code
from explain_user_code import explain_user_code
from explain_error import explain_code_error



def interactive_session():
    print("=== Python Code Generator (Ollama + CodeLlama, Local Only) ===")
    while True:
        mode = ask_input("請選擇模式 (1: 生成程式碼, 2: 出題, 3: 使用者程式碼驗證, 4: 程式碼解釋, q 離開)", "1")
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
            
            code_prompt_string = build_stdin_code_prompt(user_need, virtual_code, json_tests)
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
                                json_tests,
                                history, 
                                current_code, 
                                modification_request
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
            print("請貼上 Python 程式碼，結束輸入請輸入單獨一行 'END'。")
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
                print("[提示] 沒有輸入程式碼，取消驗證。")
                continue

            from verify_and_explain import verify_and_explain_user_code

            print("\n=== 驗證中 ===\n")
            result = verify_and_explain_user_code(user_code)

            if "錯誤" in result or "Traceback" in result or "失敗" in result:
                print("\n[警告] 程式執行失敗，開始分析...\n")
                try:
                    fallback_result = explain_code_error(user_code)
                    result += f"\n\n[分析結果]\n{fallback_result}"
                except Exception as e:
                    result += f"\n\n[分析失敗] {e}"

            print("\n=== 結果 ===\n")
            print(result)
        elif mode == "4":
            explain_user_code()
        elif mode == "5":
            print("請貼上 Python 程式碼，結束輸入請輸入單獨一行 'END'。")
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
                print("[提示] 沒有輸入程式碼，取消解釋。")
                continue

            explanation = explain_code_error(user_code)
            print("\n=== 模型解釋 ===\n")
            print(explanation)
        elif mode == "6":
            interactive_code_modification_loop()

        else:
            interactive_chat()


if __name__ == "__main__":
    try:
        interactive_session()
    except KeyboardInterrupt:
        print("\n使用者中斷，結束。")