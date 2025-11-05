import streamlit as st
import re
import json
import random
import time
from io import StringIO
from types import MappingProxyType

# 匯入 main.py 和 quiz_mode.py 所需的核心功能
# 我們保留所有後端邏輯，只替換 UI
try:
    from core import (
        generate_response, 
        extract_code_block, 
        extract_json_block, 
        parse_tests_from_text, 
        validate_main_function
    )
    from core.model_interface import (
        build_virtual_code_prompt, 
        build_test_prompt, 
        build_explain_prompt, 
        build_stdin_code_prompt, 
        build_fix_code_prompt
    )
    from core.explain_error import explain_code_error
except ImportError as e:
    st.error(f"核心模組 'core' 載入失敗: {e}")
    st.info("請確保 'core' 資料夾與此 'streamlit_app.py' 檔案位於同一目錄。")
    st.stop()

# 匯入 quiz_mode.py 的輔助函式
try:
    from quiz.quiz_mode import (
        list_obj_units, 
        load_all_coding_practice, 
        _normalize_output, 
        parse_leetcode_info, 
        get_data_structures_preamble
    )
except ImportError as e:
    st.error(f"測驗模組 'quiz' 載入失敗: {e}")
    st.info("請確保 'quiz' 資料夾與此 'streamlit_app.py' 檔案位於同一目錄。")
    st.stop()

# --- Streamlit UI 設定 ---

st.set_page_config(
    page_title="Akapychan",
    page_icon="🤖",
    layout="wide"
)

# --- 狀態初始化 ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_mode" not in st.session_state:
    st.session_state.current_mode = "chat" # 預設為一般聊天
if "mode_step" not in st.session_state:
    st.session_state.mode_step = "start"
if "app_data" not in st.session_state:
    st.session_state.app_data = {}

# --- 側邊欄：模式選擇 ---

st.sidebar.title("🤖 Akapychan AI")
st.sidebar.markdown("")

mode_options = MappingProxyType({
    "一般聊天": "chat",
    "1: 生成程式碼": "gen_code",
    "2: 出題 (測驗模式)": "quiz",
    "3: 使用者程式碼驗證": "validate",
    "4: 程式碼解釋": "explain",
    "5: 翻譯": "translate",
    "6: 程式碼建議": "suggest",
})

# 獲取當前模式的標籤
current_mode_label = [label for label, key in mode_options.items() if key == st.session_state.current_mode][0]

selected_mode_label = st.sidebar.selectbox(
    "請選擇模式：",
    options=list(mode_options.keys()),
    index=list(mode_options.keys()).index(current_mode_label), # 保持 selectbox 與狀態同步
    key="mode_selector"
)

selected_mode_key = mode_options[selected_mode_label]

# 當模式改變時，重置狀態
if st.session_state.current_mode != selected_mode_key:
    st.session_state.current_mode = selected_mode_key
    st.session_state.mode_step = "start"
    st.session_state.messages = []
    st.session_state.app_data = {} # 清空暫存數據
    
    # 根據新模式顯示歡迎訊息
    welcome_message = "HELLO"
    if selected_mode_key == "gen_code":
        welcome_message = "您好！請輸入您的程式碼需求說明，我將為您生成虛擬碼、測資、程式碼及解釋。"
    elif selected_mode_key == "quiz":
        welcome_message = "進入測驗模式。我將首先列出可用的單元。"
        try:
            units = list_obj_units()
            if not units:
                welcome_message = "⚠️ [錯誤] 找不到 'data' 資料夾或 'data' 中沒有任何單元。"
            else:
                st.session_state.app_data["quiz_units"] = units
                unit_list_str = "\n".join(f"{i+1}. {unit}" for i, unit in enumerate(units))
                welcome_message = f"請選擇單元 (輸入編號):\n\n{unit_list_str}"
                st.session_state.mode_step = "quiz_unit_selected"
        except Exception as e:
            welcome_message = f"❌ 載入測驗單元失敗: {e}"
    elif selected_mode_key == "validate":
         welcome_message = "進入程式碼驗證模式。請貼上您要驗證的 Python 程式碼。"
    elif selected_mode_key == "explain":
        welcome_message = "進入程式碼解釋模式。請貼上您要解釋的 Python 程式碼。"
    elif selected_mode_key == "translate":
        welcome_message = "進入翻譯模式。請輸入您要翻譯的文字 (中/英)。"
    elif selected_mode_key == "suggest":
        welcome_message = "進入程式碼建議模式。請貼上您的 Python 程式碼，我將提供改進建議。"
    else: # 一般聊天
        welcome_message = "您好！有什麼可以幫助您的嗎？"
        
    st.session_state.messages.append({"role": "assistant", "content": welcome_message})
    st.rerun() # 強制重新整理以顯示新模式的歡迎訊息


# --- 主聊天介面 ---

# 顯示聊天記錄
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 處理新的使用者輸入
if prompt := st.chat_input("請在這裡輸入..."):
    # 顯示並儲存使用者訊息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 根據當前模式和步驟處理輸入
    mode = st.session_state.current_mode
    step = st.session_state.mode_step
    app_data = st.session_state.app_data

    # 準備一個變數來儲存助理的*完整*回覆
    assistant_response_content = ""

    try:
        # --- 模式 1: 生成程式碼 ---
        if mode == "gen_code":
            with st.chat_message("assistant"):
                if step == "start":
                    app_data["user_need"] = prompt
                    with st.spinner("正在生成虛擬碼..."):
                        vc_prompt = build_virtual_code_prompt(prompt)
                        vc_resp = generate_response(vc_prompt)
                        app_data["virtual_code"] = vc_resp
                    
                    assistant_response_content = f"=== 模型回覆 (虛擬碼) ===\n{vc_resp}\n\n---\n是否符合需求？ (請輸入 'y' 繼續, 'n' 重新生成, 'a' 新增補充說明)"
                    st.markdown(assistant_response_content)
                    st.session_state.mode_step = "vc_confirm"

                elif step == "vc_confirm":
                    confirm = prompt.lower().strip()
                    if confirm in ("", "y", "yes"):
                        response_parts = ["好的，正在生成測資..."]
                        with st.spinner("正在生成測資..."):
                            test_prompt = build_test_prompt(app_data["user_need"])
                            test_resp = generate_response(test_prompt)
                            json_tests = extract_json_block(test_resp) or parse_tests_from_text(app_data["user_need"])
                            app_data["json_tests"] = json_tests
                        
                        response_parts.append(f"=== 模型回覆 (測資) ===\n{test_resp}")
                        if json_tests:
                            response_parts.append(f"✅ [提示] 已成功提取 {len(json_tests)} 筆測資。")
                        else:
                            response_parts.append("⚠️ [警告] 未能從模型回覆中提取 JSON 測資。")
                        
                        response_parts.append("\n正在根據虛擬碼和測資生成程式碼...")
                        
                        with st.spinner("正在生成 (stdin/stdout) 程式碼..."):
                            code_prompt = build_stdin_code_prompt(
                                app_data["user_need"], 
                                app_data["virtual_code"], 
                                ai_generated_tests=json_tests
                            )
                            code_resp = generate_response(code_prompt)
                        
                        code_or_list = extract_code_block(code_resp)
                        code = code_or_list[0] if isinstance(code_or_list, list) and code_or_list else (code_or_list if isinstance(code_or_list, str) else None)
                        
                        if code:
                            app_data["current_code"] = code
                            response_parts.append("=== 模型回覆 (程式碼) ===")
                            response_parts.append(f"```python\n{code}\n```")
                            
                            with st.spinner("正在生成程式碼解釋..."):
                                explain_prompt = build_explain_prompt(app_data["user_need"], code)
                                explain_resp = generate_response(explain_prompt)
                            response_parts.append(f"=== 模型回覆 (解釋) ===\n{explain_resp}")
                            response_parts.append("---\n是否要執行程式碼驗證？ (請輸入 'y' 驗證, 'n' 略過)")
                            st.session_state.mode_step = "run_test_confirm"
                        else:
                            response_parts.append("❌ [錯誤] 未能生成程式碼。")
                            st.session_state.mode_step = "start" # 重置

                        assistant_response_content = "\n\n".join(response_parts)
                        st.markdown(assistant_response_content)

                    elif confirm in ("n", "no"):
                        assistant_response_content = "[提示] 請重新輸入您的需求說明。"
                        st.markdown(assistant_response_content)
                        st.session_state.mode_step = "start"
                    
                    elif confirm == "a":
                        assistant_response_content = "請輸入補充說明："
                        st.markdown(assistant_response_content)
                        st.session_state.mode_step = "vc_amend"

                elif step == "vc_amend":
                    extra_info = prompt
                    app_data["user_need"] += f"\n(補充說明: {extra_info})"
                    st.markdown("[提示] 已加入補充說明，重新生成虛擬碼...")
                    with st.spinner("正在重新生成虛擬碼..."):
                        vc_prompt = build_virtual_code_prompt(app_data["user_need"])
                        vc_resp = generate_response(vc_prompt)
                        app_data["virtual_code"] = vc_resp
                    
                    assistant_response_content = f"=== 模型回覆 (虛擬碼) ===\n{vc_resp}\n\n---\n是否符合需求？ (請輸入 'y' 繼續, 'n' 重新生成, 'a' 新增補充說明)"
                    st.markdown(assistant_response_content)
                    st.session_state.mode_step = "vc_confirm"

                elif step == "run_test_confirm":
                    code = app_data.get("current_code")
                    json_tests = app_data.get("json_tests")
                    response_parts = []
                    
                    if prompt.lower().strip() in ("y", "yes", ""):
                        if not code:
                            response_parts.append("❌ 找不到程式碼，無法驗證。")
                        else:
                            response_parts.append("[驗證中] 正在使用 AI 生成的測資逐一驗證...")
                            all_passed = True
                            validation_details = []
                            if not json_tests:
                                st.warning("[警告] 找不到 AI 生成的 JSON 測資。僅執行一次 (無輸入)...")
                                success, output_msg = validate_main_function(code, stdin_input=None, expected_output=None)
                                validation_details.append(f"**執行結果 (無輸入): {'成功' if success else '失敗'}**\n```\n{output_msg}\n```")
                            else:
                                results = []
                                for i, test in enumerate(json_tests):
                                    test_input_val, test_output_val = test if (isinstance(test, list) and len(test) == 2) else (None, None)
                                    if test_input_val is None and test_output_val is None:
                                        results.append(f"--- 測試案例 {i+1} [跳過] ---\n  [警告] 測資格式不符: {repr(test)}")
                                        all_passed = False
                                        continue
                                    
                                    test_input_str = str(test_input_val) if test_input_val is not None else None
                                    test_output_str = str(test_output_val) if test_output_val is not None else None

                                    success, output_msg = validate_main_function(
                                        code=code,
                                        stdin_input=test_input_str,
                                        expected_output=test_output_str
                                    )
                                    result_status = "[通過]" if success else "[失敗]"
                                    if not success: all_passed = False
                                    results.append(f"--- 測試案例 {i+1} {result_status} ---\n  Input: {repr(test_input_val)}\n  Expected: {repr(test_output_val)}\n  詳細資訊/執行結果:\n{output_msg}")
                                
                                validation_details.append("\n\n".join(results))
                            
                            response_parts.append("\n".join(validation_details))
                            summary = "✅ 總結: [成功] 所有測資均已通過。" if all_passed else "❌ 總結: [失敗] 部分測資未通過。"
                            response_parts.append(summary)
                    else:
                        response_parts.append("好的，略過驗證。")
                    
                    response_parts.append("---\n是否要進入互動式修改模式？ (請輸入 'y' 進入, 'n' 結束)")
                    assistant_response_content = "\n\n".join(response_parts)
                    st.markdown(assistant_response_content)
                    st.session_state.mode_step = "modify_confirm"

                elif step == "modify_confirm":
                    if prompt.lower().strip() in ("y", "yes"):
                        assistant_response_content = "=== 進入互動式修改模式 ===\n請輸入您的修改需求 (或輸入 'VERIFY' 驗證, 'EXPLAIN' 解釋, 'QUIT' 結束)"
                        app_data["history"] = [f"初始需求: {app_data['user_need']}"]
                        st.session_state.mode_step = "modifying"
                    else:
                        assistant_response_content = "好的，程式碼生成完畢。您可以從側邊欄切換新模式。"
                        st.session_state.mode_step = "start"
                    st.markdown(assistant_response_content)
                
                elif step == "modifying":
                    mod_request = prompt.strip()
                    response_parts = []
                    
                    if mod_request.upper() == "QUIT":
                        assistant_response_content = f"=== 結束修改模式 ===\n最終程式碼如下：\n```python\n{app_data.get('current_code', '# 無程式碼')}\n```\n\n您可以從側邊欄切換新模式。"
                        st.session_state.mode_step = "start"
                    
                    elif mod_request.upper() in ("VERIFY", "V"):
                        response_parts.append("[驗證中] 正在驗證當前程式碼...")
                        code = app_data.get("current_code")
                        json_tests = app_data.get("json_tests")
                        all_passed = True
                        validation_details = []
                        if not json_tests:
                            success, output_msg = validate_main_function(code, stdin_input=None, expected_output=None)
                            validation_details.append(f"**執行結果 (無輸入): {'成功' if success else '失敗'}**\n```\n{output_msg}\n```")
                        else:
                            results = []
                            for i, test in enumerate(json_tests):
                                test_input_val, test_output_val = test if (isinstance(test, list) and len(test) == 2) else (None, None)
                                test_input_str = str(test_input_val) if test_input_val is not None else None
                                test_output_str = str(test_output_val) if test_output_val is not None else None
                                success, output_msg = validate_main_function(code=code, stdin_input=test_input_str, expected_output=test_output_str)
                                result_status = "[通過]" if success else "[失敗]"
                                if not success: all_passed = False
                                results.append(f"--- 測試案例 {i+1} {result_status} ---\n  Input: {repr(test_input_val)}\n  Expected: {repr(test_output_val)}\n  詳細資訊/執行結果:\n{output_msg}")
                            validation_details.append("\n\n".join(results))
                        
                        response_parts.append("\n".join(validation_details))
                        summary = "✅ 總結: [成功] 所有測資均已通過。" if all_passed else "❌ 總結: [失敗] 部分測資未通過。"
                        response_parts.append(summary)
                        response_parts.append("---\n請繼續輸入修改需求 (或 'VERIFY', 'EXPLAIN', 'QUIT')")
                        assistant_response_content = "\n\n".join(response_parts)
                        
                    elif mod_request.upper() in ("EXPLAIN", "E"):
                        with st.spinner("正在解釋當前程式碼..."):
                            explain_prompt = build_explain_prompt(app_data["user_need"], app_data["current_code"])
                            explain_resp = generate_response(explain_prompt)
                        assistant_response_content = f"=== 程式碼解釋 ===\n{explain_resp}\n\n---\n請繼續輸入修改需求 (或 'VERIFY', 'EXPLAIN', 'QUIT')"

                    else: # 實際的修改需求
                        app_data["history"].append(f"修改: {mod_request}")
                        with st.spinner(f"正在根據 '{mod_request}' 修正程式碼..."):
                            fix_prompt = build_fix_code_prompt(
                                app_data["user_need"], 
                                app_data["virtual_code"], 
                                app_data["json_tests"],
                                app_data["history"],
                                app_data["current_code"],
                                mod_request
                            )
                            fix_resp = generate_response(fix_prompt)
                        
                        response_parts.append("=== 模型回覆 (新版程式碼) ===")
                        code_or_list = extract_code_block(fix_resp)
                        new_code = code_or_list[0] if isinstance(code_or_list, list) and code_or_list else (code_or_list if isinstance(code_or_list, str) else None)
                        
                        if new_code:
                            app_data["current_code"] = new_code
                            response_parts.append(f"```python\n{new_code}\n```")
                        else:
                            response_parts.append("⚠️ [警告] 模型無法生成修正後的程式碼。")
                        response_parts.append("---\n請繼續輸入修改需求 (或 'VERIFY', 'EXPLAIN', 'QUIT')")
                        assistant_response_content = "\n\n".join(response_parts)
                    
                    st.markdown(assistant_response_content)

        # --- 模式 2: 出題 (測驗模式) ---
        elif mode == "quiz":
            with st.chat_message("assistant"):
                if step == "quiz_unit_selected":
                    units = app_data.get("quiz_units", [])
                    try:
                        sel_idx = int(prompt.strip()) - 1
                        if not (0 <= sel_idx < len(units)):
                            assistant_response_content = "⚠️ 輸入無效，請輸入列表中的編號。"
                        else:
                            unit = units[sel_idx]
                            app_data["selected_unit"] = unit
                            with st.spinner(f"正在從 {unit} 載入題庫..."):
                                practices = load_all_coding_practice(unit=unit)
                            if not practices:
                                assistant_response_content = "⚠️ 此單元沒有練習題。"
                                st.session_state.mode_step = "start" # 重置
                            else:
                                q = random.choice(practices)
                                app_data["quiz_q"] = q
                                example_to_run = None
                                examples_data = q.get("examples")
                                if isinstance(examples_data, list) and examples_data:
                                    example_to_run = examples_data[0]
                                elif isinstance(examples_data, dict):
                                    example_to_run = examples_data
                                app_data["quiz_example"] = example_to_run

                                response_parts = [f"=== 題目 ===\n**單元:** {unit}\n**標題:** {q['title']}\n**描述:** {q['description']}\n"]
                                if example_to_run:
                                    response_parts.append(f"**範例:**\n```json\n{json.dumps(example_to_run, indent=2)}\n```")
                                response_parts.append("---\n請輸入您的 Python 解答 (若為 LeetCode 題，請包含 `class Solution: ...`)")
                                assistant_response_content = "\n\n".join(response_parts)
                                st.session_state.mode_step = "quiz_code_submitted"
                    except ValueError:
                         assistant_response_content = "⚠️ 輸入無效，請輸入一個數字編號。"
                    st.markdown(assistant_response_content)
                
                elif step == "quiz_code_submitted":
                    user_code = prompt
                    q = app_data.get("quiz_q")
                    example_to_run = app_data.get("quiz_example")
                    response_parts = []
                    
                    if not q:
                        response_parts.append("❌ 找不到題目資料，請重新開始。")
                    elif not example_to_run:
                        response_parts.append("ℹ️ [提示] 此題無範例，跳過驗證。")
                    else:
                        is_leetcode_format = "class Solution" in q.get("solution", "")
                        harness_code_to_analyze = user_code
                        success = False
                        output_msg = ""
                        
                        st.markdown("--- \n[驗證中...]")

                        if is_leetcode_format:
                            test_input_str = str(example_to_run.get("input", ""))
                            test_output_str = str(example_to_run.get("output", ""))
                            reference_solution = q.get("solution")
                            func_name, arg_names, input_definitions = parse_leetcode_info(reference_solution, test_input_str)
                            
                            if func_name is None:
                                output_msg = "[跳過] ❌\n[提示] 此 LeetCode 題目格式為類別實例化或無法解析，目前驗證器尚不支援。"
                            else:
                                harness_code = f"{get_data_structures_preamble()}\n{user_code}\n" \
                                               f"import sys\nimport json\n\ndef auto_convert_output(result):\n    if isinstance(result, ListNode):\n        return nodes_to_list(result)\n    if isinstance(result, TreeNode):\n        return tree_to_list(result)\n    return result\n\ndef run_test_harness():\n" \
                                               f"    try:\n        {input_definitions}\n" \
                                               f"        instance = Solution()\n" \
                                               f"        result = instance.{func_name}({', '.join(arg_names)})\n" \
                                               f"        final_result = auto_convert_output(result)\n" \
                                               f"        print(final_result)\n    except Exception as e:\n" \
                                               f"        print(f'HarnessExecutionError: {{e}}', file=sys.stderr)\n" \
                                               f"run_test_harness()"
                                harness_code_to_analyze = harness_code
                                exec_success, raw_output_str = validate_main_function(code=harness_code, stdin_input=None, expected_output=None)
                                if exec_success:
                                    norm_expected = _normalize_output(test_output_str)
                                    norm_actual = _normalize_output(raw_output_str)
                                    if norm_expected == norm_actual:
                                        success = True
                                        output_msg = f"**Actual Output:**\n```\n{raw_output_str}\n```"
                                    else:
                                        output_msg = f"**Actual Output:**\n```\n{raw_output_str}\n```\n**[Output Mismatch (Normalized)]**\nExpected: `{repr(norm_expected)}`\nGot:      `{repr(norm_actual)}`"
                                else:
                                    output_msg = f"**Execution Error:**\n```\n{raw_output_str}\n```"
                        else: # stdin/stdout 格式
                            test_input_str = str(example_to_run.get("input", ""))
                            test_output_str = str(example_to_run.get("output", ""))
                            exec_success, raw_output_str = validate_main_function(code=user_code, stdin_input=test_input_str, expected_output=None)
                            if exec_success:
                                norm_expected = _normalize_output(test_output_str)
                                norm_actual = _normalize_output(raw_output_str)
                                if norm_expected == norm_actual:
                                    success = True
                                    output_msg = f"**Actual Output:**\n```\n{raw_output_str}\n```"
                                else:
                                    output_msg = f"**Actual Output:**\n```\n{raw_output_str}\n```\n**[Output Mismatch (Normalized)]**\nExpected: `{repr(norm_expected)}`\nGot:      `{repr(norm_actual)}`"
                            else:
                                output_msg = f"**Execution Error:**\n```\n{raw_output_str}\n```"

                        if success:
                            response_parts.append("--- \n**結果: [成功] ✅**\n" + output_msg)
                        else:
                            response_parts.append("--- \n**結果: [錯誤] ❌**\n" + output_msg)
                            with st.spinner("程式執行失敗，開始分析錯誤..."):
                                try:
                                    analysis_result = explain_code_error(harness_code_to_analyze)
                                    response_parts.append("=== 錯誤分析 ===\n" + analysis_result)
                                except Exception as e:
                                    response_parts.append(f"⚠️ [分析失敗] {e}")
                    
                    response_parts.append(f"=== 參考解答 ===\n```python\n{q.get('solution', '[無解答]')}\n```")
                    response_parts.append("---\n測驗完畢。您可以從側邊欄切換模式，或再次發送訊息以重新出題。")
                    
                    assistant_response_content = "\n\n".join(response_parts)
                    st.markdown(assistant_response_content)
                    
                    # 儲存主要回覆
                    st.session_state.messages.append({"role": "assistant", "content": assistant_response_content})

                    # 觸發下一個問題
                    st.session_state.mode_step = "start"
                    try:
                        units = list_obj_units()
                        st.session_state.app_data["quiz_units"] = units
                        unit_list_str = "\n".join(f"{i+1}. {unit}" for i, unit in enumerate(units))
                        # 這是*第二則*訊息，單獨附加
                        assistant_response_content = f"請選擇單元 (輸入編號):\n\n{unit_list_str}"
                        st.session_state.messages.append({"role": "assistant", "content": assistant_response_content})
                        st.session_state.mode_step = "quiz_unit_selected"
                    except Exception as e:
                        assistant_response_content = f"❌ 載入測驗單元失敗: {e}"
                        st.session_state.messages.append({"role": "assistant", "content": assistant_response_content})
                    
                    st.rerun() # 需要 rerun 來顯示第二則訊息
                    
        # --- 模式 3: 使用者程式碼驗證 ---
        elif mode == "validate":
            with st.chat_message("assistant"):
                if step == "start":
                    app_data["user_code"] = prompt
                    assistant_response_content = "感謝您提供程式碼。現在，請輸入這段程式碼的「需求說明」，AI 將以此生成測資。\n(如果留空，將僅執行一次程式)"
                    st.markdown(assistant_response_content)
                    st.session_state.mode_step = "v_need_submitted"
                
                elif step == "v_need_submitted":
                    user_need = prompt.strip()
                    user_code = app_data.get("user_code")
                    response_parts = []
                    
                    if not user_code:
                        response_parts.append("❌ 找不到程式碼，請重新開始。")
                    else:
                        json_tests = []
                        if user_need:
                            with st.spinner("正在根據您的需求說明生成測資..."):
                                test_prompt = build_test_prompt(user_need)
                                test_resp = generate_response(test_prompt)
                                json_tests = extract_json_block(test_resp) or parse_tests_from_text(user_need)
                            response_parts.append(f"=== 模型回覆 (測資) ===\n{test_resp}")
                            if json_tests:
                                response_parts.append(f"✅ [提示] 已成功提取 {len(json_tests)} 筆測資。")
                            else:
                                response_parts.append("⚠️ [警告] 未能從模型回覆中提取 JSON 測資。")
                        
                        if json_tests:
                            response_parts.append("[驗證中] 正在使用 AI 生成的測資逐一驗證您的程式碼...")
                            all_passed = True
                            failed_outputs = []
                            results = []
                            for i, test in enumerate(json_tests):
                                test_input_val, test_output_val = test if (isinstance(test, list) and len(test) == 2) else (None, None)
                                if test_input_val is None and test_output_val is None:
                                    results.append(f"--- 測試案例 {i+1} [跳過] ---\n  [警告] 測資格式不符: {repr(test)}")
                                    all_passed = False
                                    continue
                                
                                test_input_str = str(test_input_val) if test_input_val is not None else ""
                                test_output_str = str(test_output_val) if test_output_val is not None else None
                                success, output_msg = validate_main_function(
                                    code=user_code,
                                    stdin_input=test_input_str,
                                    expected_output=test_output_str
                                )
                                result_status = "[通過] ✅" if success else "[失敗] ❌"
                                if not success: 
                                    all_passed = False
                                    failed_outputs.append(f"案例 {i+1} (Input: {repr(test_input_str)}):\n{output_msg}")
                                results.append(f"--- 測試案例 {i+1} {result_status} ---\n  Input: {repr(test_input_val)}\n  Expected: {repr(test_output_val)}\n  詳細資訊/執行結果:\n{output_msg}")
                            
                            response_parts.append("\n\n".join(results))
                            
                            if all_passed:
                                response_parts.append("✅ 總結: [成功] 您的程式碼已通過所有 AI 生成的測資。")
                            else:
                                response_parts.append("❌ 總結: [失敗] 您的程式碼未通過部分測資。")
                                with st.spinner("程式驗證失敗，開始分析..."):
                                    try:
                                        analysis_result = explain_code_error(user_code)
                                        response_parts.append(f"=== 程式碼分析 ===\n{analysis_result}")
                                        if failed_outputs:
                                            response_parts.append(f"**(首個失敗詳情: {failed_outputs[0]})**")
                                    except Exception as e:
                                        response_parts.append(f"⚠️ [分析失敗] {e}")

                        else: # 沒有測資，僅執行一次
                            response_parts.append("[驗證中] 正在執行一次程式 (無輸入)...")
                            success, result_msg = validate_main_function(user_code, stdin_input=None, expected_output=None)
                            if success:
                                response_parts.append(f"=== 程式執行成功 ===\n**STDOUT 輸出:**\n```\n{result_msg}\n```")
                            else:
                                response_parts.append(f"=== 程式執行失敗 ===\n**STDERR 或錯誤訊息:**\n```\n{result_msg}\n```")
                                with st.spinner("程式執行失敗，開始分析..."):
                                    try:
                                        analysis_result = explain_code_error(user_code)
                                        response_parts.append(f"=== 程式碼分析 ===\n{analysis_result}")
                                    except Exception as e:
                                        response_parts.append(f"⚠️ [分析失敗] {e}")

                    response_parts.append("---\n驗證完畢。請貼上新的程式碼以開始下一次驗證。")
                    assistant_response_content = "\n\n".join(response_parts)
                    st.markdown(assistant_response_content)
                    st.session_state.mode_step = "start"

        # --- 模式 4: 程式碼解釋 ---
        elif mode == "explain":
            with st.chat_message("assistant"):
                user_code = prompt
                with st.spinner("正在分析程式碼並生成解釋..."):
                    explain_prompt_str = build_explain_prompt("請詳細解釋這段程式碼的功能、邏輯和潛在問題。", user_code)
                    explain_resp = generate_response(explain_prompt_str)
                assistant_response_content = f"=== 程式碼解釋 ===\n{explain_resp}\n\n---\n解釋完畢。請貼上新的程式碼以開始下一次解釋。"
                st.markdown(assistant_response_content)
                st.session_state.mode_step = "start"

        # --- 模式 5: 翻譯 ---
        elif mode == "translate":
            with st.chat_message("assistant"):
                text_to_translate = prompt
                prompt_string = f"""
                Detect the language of the following text and translate it to the other language (English or Traditional Chinese).
                
                Text to translate:
                "{text_to_translate}"
                
                Translation:
                """
                with st.spinner("翻譯中..."):
                    translated_text = generate_response(prompt_string)
                assistant_response_content = f"=== 翻譯結果 ===\n{translated_text}\n\n---\n翻譯完畢。請輸入新的文字以開始下一次翻譯。"
                st.markdown(assistant_response_content)
                st.session_state.mode_step = "start"

        # --- 模式 6: 程式碼建議 ---
        elif mode == "suggest":
            with st.chat_message("assistant"):
                user_code = prompt
                prompt_string = f"""
                Analyze the following Python code and provide suggestions for improvement. 
                Focus on potential bugs, style issues (PEP 8), optimizations, and readability.

                Code:
                ```python
                {user_code}
                ```

                Suggestions:
                """
                with st.spinner("正在分析程式碼並提供建議..."):
                    suggestion_resp = generate_response(prompt_string)
                assistant_response_content = f"=== 程式碼建議 ===\n{suggestion_resp}\n\n---\n建議完畢。請貼上新的程式碼以獲取建議。"
                st.markdown(assistant_response_content)
                st.session_state.mode_step = "start"

        # --- 預設: 一般聊天 ---
        else: # mode == "chat"
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    # 這裡可以擴展為傳遞聊天記錄
                    # 簡易版：
                    # history_context = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages])
                    # response = generate_response(f"{history_context}\nuser: {prompt}\nassistant:")
                    
                    # 單輪回應版：
                    response = generate_response(prompt)
                    
                assistant_response_content = response
                st.markdown(assistant_response_content)
                st.session_state.mode_step = "start"
    
    except Exception as e:
        assistant_response_content = f"❌ 處理時發生嚴重錯誤: {e}"
        st.error(assistant_response_content)
        st.session_state.mode_step = "start"

    # --- (*** 關鍵修正 ***) ---
    # 在所有模式的邏輯結束後，將助理的最終回覆儲存到 session_state
    # (測驗模式除外，它有自己的 reran 邏輯來處理多條訊息)
    if mode != "quiz" and assistant_response_content:
        st.session_state.messages.append({"role": "assistant", "content": assistant_response_content})

    # 儲存更新的 app_data
    st.session_state.app_data = app_data
    
    # 在處理完一個 prompt 後，重新整理頁面
    # 這會使頂部的 "for message in st.session_state.messages:" 迴圈
    # 重新繪製*包含*剛剛新增的助理訊息的完整聊天記錄
    if mode != "quiz": # 測驗模式有自己的 rerun 邏輯
        st.rerun()