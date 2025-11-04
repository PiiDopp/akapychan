import subprocess
import os
import time
from core.io_utils import ThinkingDots, ask_input
from typing import List, Optional, Tuple, Dict
from core.code_extract import extract_code_block
from core.validators import validate_main_function
import re

from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
OLLAMA_API = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = "gpt-oss"


# ===================== Prompt Builders =====================

def build_virtual_code_prompt(user_need: str) -> str:
    """
    產生虛擬碼 (Virtual Code)，類似流程圖的描述方式
    """
    return (
        "用繁體中文回答。\n"
        "你是一個虛擬碼生成助理。\n"
        "任務：根據使用者的自然語言需求，**逐行地**產生對應的虛擬碼 (Virtual Code)，並在每行虛擬碼之後**立即**提供該行的**簡短、直觀的解釋**。\n"
        "⚠️ 請勿輸出實際程式碼，只輸出結構化的步驟。\n\n"
        "**輸出格式要求**：\n"
        "1.  **逐行**輸出。\n"
        "2.  **每行**必須包含：`虛擬碼步驟` + `[空格]` + `// 解釋/說明`。\n"
        "3.  使用虛擬碼的箭頭 (`→`, `Yes →`, `No →`) 和結構 (`Start`, `End`, `Decision:`)。\n\n"
        "**格式範例**：\n"
        "```\n"
        "Start // 程式開始執行\n"
        "→ Step 1: 輸入使用者數字 // 從使用者處取得一個數值\n"
        "→ Decision: 如果數字大於 0? // 檢查數值是否為正\n"
        "    Yes → Step 2: 輸出 '正數' // 如果是正數，顯示該訊息\n"
        "    No  → Decision: 如果數字等於 0? // 如果不是正數，檢查是否為零\n"
        "        Yes → Step 3: 輸出 '零' // 數字是零，顯示該訊息\n"
        "        No  → Step 4: 輸出 '負數' // 否則數值是負數\n"
        "End // 程式執行結束\n"
        "```\n\n"
        f"使用者需求:\n{user_need}\n\n請根據**輸出格式要求**產生虛擬碼和逐行解釋："
    )

def build_code_prompt(user_need: str) -> str:
    """
    只產生 Python 程式碼，且程式碼必須包含 main() 函式。
    """
    return (
        "用繁體中文回答。\n"
        "你是程式碼生成助理。\n"
        "任務：依據使用者需求產生正確可執行的 Python 程式碼，並加上白話註解。\n\n"
        "⚠️ **重要**：請僅輸出一個 Python 程式碼區塊，絕對不要輸出任何額外文字或解釋。\n"
        "程式碼必須：\n"
        "  1) 定義一個 `def main():` 函式作為程式進入點，\n"
        "  2) 在 `main()` 函式內，**必須包含具體的測試案例程式碼**，展示如何呼叫你定義的函式，並用 `print()` 輸出結果。\n"
        "  3) 在檔案尾端包含 `if __name__ == \"__main__\":\\n    main()` 以便直接執行，\n"
        "  4) 包含必要的白話註解以說明主要步驟。\n\n"
        "輸出格式範例（務必遵守）：\n"
        "```python\n"
        "# 你的程式碼（包含 def main(): 與 if __name__ == \"__main__\": main() ）\n"
        "```\n\n"
        f"使用者需求:\n{user_need}\n\n"
        "請產生符合上述要求的 Python 程式碼："
    )



def build_test_prompt(user_need: str) -> str:
    """
    只產生測資
    """
    return (
        "用繁體中文回答。\n"
        "你是一個測資生成助理。\n"
        "任務：根據使用者需求，產生 3~5 組測資，格式如下：\n"
        "```json\n[[輸入, 輸出], [輸入, 輸出], ...]\n```\n"
        f"\n使用者需求:\n{user_need}\n\n請產生測資："
    )


def build_explain_prompt(user_need: str, code: str) -> str:
    """
    只解釋程式碼，避免混進程式或測資
    """
    return (
        "用繁體中文回答。\n"
        "你是一個程式解釋助理。\n"
        "任務：解釋下面的 Python 程式碼，請用白話淺顯的方式，避免使用專業術語。\n\n"
        f"使用者需求:\n{user_need}\n\n"
        f"程式碼:\n```python\n{code}\n```\n\n"
        "請輸出程式碼的功能說明："
    )

def interactive_langchain_chat():
    """
    使用 LangChain 的 ConversationChain 實現多輪對話模式。
    """
    print("=== 模型互動聊天模式 (LangChain 多輪對話) ===")
    print(f"使用的模型: {MODEL_NAME}")
    print("對話會記住歷史紀錄。結束請輸入 'quit'。")

    try:
        llm = OllamaLLM(model=MODEL_NAME)

        # 2. 定義 prompt 模板
        prompt = ChatPromptTemplate.from_template("{input}")

        # 3. 建立對話記憶
        history = ChatMessageHistory()

        # 4. 建立對話鏈 (取代 ConversationChain)
        conversation = RunnableWithMessageHistory(
            prompt | llm,
            lambda session_id: history,
            input_messages_key="input",
        )

        while True:
            user_input = input("你 (輸入 'quit' 結束): ").strip()

            if user_input.lower() == "quit":
                print("離開互動聊天模式。")
                break

            if not user_input:
                continue
            
            # 使用 LangChain 的 ConversationChain 進行對話
            try:
                # 顯示思考點點
                spinner = ThinkingDots("模型思考中")
                start_time = time.perf_counter()
                spinner.start()

                # 呼叫對話鏈
                # LangChain 會自動處理 prompt 模板、歷史紀錄的插入
                resp = conversation.invoke({"input": user_input})['response']

                spinner.stop()
                duration = time.perf_counter() - start_time
                print(f"[資訊] 模型思考時間: {duration:.3f} 秒")
                
                print("\n=== 模型回覆 ===\n")
                print(resp)
                print("\n---------------------------------\n")

            except Exception as e:
                spinner.stop()
                print(f"\n[錯誤] LangChain 模型回覆失敗：{e}")
                print("請檢查 Ollama 服務是否啟動，以及模型是否已 Pull。")

    except ImportError:
        print("\n[錯誤] 缺少 LangChain 相關套件。請執行 'pip install langchain langchain-community'。")
    except Exception as e:
        print(f"\n[錯誤] 初始化 LangChain 失敗: {e}")
        print("請確保 Ollama 服務已啟動。")

def interactive_chat():
    """
    與模型進行互動式聊天或程式碼解釋。
    使用者可輸入自然語言或貼上 Python 程式碼。
    結束請輸入 'END'。
    """
    print("=== 模型互動聊天模式 ===")
    print("請輸入需求或程式碼，多行輸入，結束請輸入單獨一行 'END'。")
    print("輸入 'quit' 離開。")

    while True:
        lines = []
        while True:
            line = input()
            if line.strip().lower() in ("end", "quit"):
                break
            lines.append(line)

        if not lines:
            print("[提示] 沒有輸入任何內容。")
            continue

        # 若使用者輸入 quit 結束
        if lines and lines[0].strip().lower() == "quit":
            print("離開互動聊天模式。")
            break

        user_input = "\n".join(lines).strip()

        # 偵測是否貼了 Python 程式碼
        if "def " in user_input or "print(" in user_input or "for " in user_input:
            print("\n[提示] 偵測到 Python 程式碼，進入解釋模式...\n")
            prompt = build_explain_prompt("使用者貼上的程式碼", user_input)
        else:
            # 為基礎聊天模式加入助教身份
            prompt = (
                "用繁體中文回答。\n"
                "你是一位友善且專業的程式學習助教。\n"
                "請用白話、簡單易懂的方式回答使用者的程式相關問題。\n\n"
                f"使用者問題：\n{user_input}"
            )

        try:
            resp = generate_response(prompt)
            print("\n=== 模型回覆 ===\n")
            print(resp)
            print("\n---------------------------------\n")
        except Exception as e:
            print(f"[錯誤] 模型回覆失敗：{e}")



# ===================== 模型呼叫 =====================

def call_ollama_cli(prompt: str, model: str = MODEL_NAME) -> str:
    """
    透過 Ollama CLI 呼叫模型
    """
    try:
        proc = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=300
        )
        return proc.stdout.strip() or proc.stderr.strip()
    except Exception as e:
        return f"[CLI 呼叫失敗] {e}"


def generate_response(prompt: str) -> str:
    """
    包裝：呼叫模型並顯示思考時間
    """
    spinner = ThinkingDots("模型思考中")
    start_time = time.perf_counter()
    spinner.start()
    resp = call_ollama_cli(prompt)
    spinner.stop()
    duration = time.perf_counter() - start_time
    print(f"[資訊] 模型思考時間: {duration:.3f} 秒")
    return resp or "錯誤：無法連到 Ollama。"

def interactive_code_modification_loop():
    print("=== 互動式程式碼開發與修正模式 (生成/修正/解釋) ===")

    # 1. 取得初始需求
    print("請輸入您的程式碼需求，多行輸入，結束請輸入單獨一行 'END'。")
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
        return

    current_code = ""
    history = [f"初始需求: {user_need}"]

    # 2. 初始生成
    print("\n[第一步] 產生初始程式碼...")

    # --- (可選) 略過虛擬碼步驟，直接生成程式碼 ---
    # 如果需要虛擬碼步驟，可以取消註解以下程式碼並修改邏輯
    # vc_prompt = build_virtual_code_prompt(user_need)
    # vc_resp = generate_response(vc_prompt)
    # print("\n=== 模型回覆 (虛擬碼) ===\n", vc_resp)
    # ---------------------------------------------

    code_prompt = build_code_prompt(user_need)
    code_resp = generate_response(code_prompt)

    # 處理 extract_code_block 可能返回 list 的問題
    code_or_list = extract_code_block(code_resp)
    if isinstance(code_or_list, list) and code_or_list:
        current_code = code_or_list[0]
    elif isinstance(code_or_list, str):
        current_code = code_or_list
    else:
        current_code = "" # 設為空字串

    if not current_code:
        print("[錯誤] 模型無法生成程式碼，請重試。")
        return

    print("\n=== 程式碼 (初始版本) ===\n")
    print(f"```python\n{current_code}\n```")

    # 3. 進入修正迴圈
    while True:
        print("\n" + "="*40)
        print("請輸入您的下一步操作：")
        print("  - [修改/優化/重構]：輸入您的需求說明 (例如: '請將迴圈改為列表推導式')")
        print("  - [驗證]：輸入 'VERIFY' 或 'V' (執行程式並檢查錯誤/邏輯)") # 修改說明
        print("  - [解釋]：輸入 'EXPLAIN' 或 'E' (取得當前程式碼的白話解釋)") # 修改說明
        print("  - [完成]：輸入 'QUIT' (結束開發，儲存最終程式碼)")
        print("="*40)

        user_input = input("您的操作 (或修改需求): ").strip()

        if user_input.upper() == "QUIT":
            print("\n開發模式結束。最終程式碼如下：")
            print(f"```python\n{current_code}\n```")
            break

        if user_input.upper() in ("VERIFY", "V"): # 修改判斷
            print("\n[驗證中] 執行程式碼並檢查錯誤...")
            # 假設 validate_main_function 返回 (bool, str) 分別表示成功與否和輸出/錯誤訊息
            success, validation_result = validate_main_function(current_code) # 修改接收方式
            print("\n=== 程式執行/錯誤報告 ===\n")
            print(validation_result)

            # 如果執行失敗，且 validation_result 包含錯誤訊息 (可以進一步判斷)
            # 這裡簡化，直接假設模型可能提供修正建議
            # 注意：原始程式碼中 validate_main_function 不直接調用模型解釋錯誤並提供修正版
            # 這部分邏輯需要依賴 validate_main_function 的實際行為或外部錯誤處理
            # 以下為示意性代碼，假設 validation_result 可能包含修正建議的標記
            if not success and "修正版程式" in validation_result: # 示意性判斷
                 temp_code = extract_code_block(validation_result)
                 if temp_code:
                     print("\n[提示] 模型提供了修正建議。是否要將當前程式碼替換為修正版？(y/n): ", end="")
                     choice = input().strip().lower()
                     if choice in ["y", "yes", "是", "好"]:
                         current_code = temp_code
                         history.append("自動採納模型修正版。")
                         print("\n[成功] 已採納修正版程式碼。")
                         print(f"```python\n{current_code}\n```")
                     else:
                         print("\n[提示] 已忽略修正建議，您可手動提供修改需求。")

        elif user_input.upper() in ("EXPLAIN", "E"): # 修改判斷
            print("\n[解釋中] 產生程式碼解釋...")
            explain_prompt = build_explain_prompt(user_need, current_code)
            explain_resp = generate_response(explain_prompt)
            print("\n=== 程式碼解釋 ===\n")
            print(explain_resp)

        else: # 修正需求
            modification_request = user_input
            print(f"\n[修正中] 正在根據您的要求 '{modification_request}' 修正程式碼...")

            # 構建修正提示
            fix_prompt = build_code_prompt(
                f"請根據以下歷史需求與當前程式碼，進行修正和重構：\n"
                f"--- 初始需求 ---\n"
                f"{user_need}\n"
                f"--- 當前程式碼 ---\n"
                f"```python\n{current_code}\n```\n"
                f"--- 新增修改需求 ---\n"
                f"{modification_request}\n"
                f"請確保輸出只有一個完整的 Python 程式碼區塊。"
            )

            fix_resp = generate_response(fix_prompt)
            # 處理 extract_code_block 可能返回 list 的問題
            new_code_or_list = extract_code_block(fix_resp)
            if isinstance(new_code_or_list, list) and new_code_or_list:
                new_code = new_code_or_list[0]
            elif isinstance(new_code_or_list, str):
                new_code = new_code_or_list
            else:
                new_code = None

            if new_code:
                current_code = new_code
                history.append(f"上次修改: {modification_request}")
                print("\n=== 程式碼 (新版本) ===\n")
                print(f"```python\n{current_code}\n```")
            else:
                print("[警告] 模型無法生成修正後的程式碼。請重試或輸入更明確的指令。")

    return current_code # 函數應回傳最終代碼

def build_stdin_code_prompt(user_need: str, virtual_code: str, ai_generated_tests: Optional[List[Tuple[str, str]]],solution: Optional[str] = None,file_examples: Optional[List[Dict[str, str]]] = None) -> str:
    """
    (MODIFIED) 建立一個專門用於生成 stdin/stdout 程式碼的提示。
    採用 testrun.py 的提示邏輯。
    """
    code_prompt_lines = [
        "用繁體中文回答。\n你是程式碼生成助理。\n任務：依據使用者需求、虛擬碼、範例，產生正確可執行的 Python 程式碼，並加上白話註解。\n",
        f"原始需求：\n{user_need}\n",
        f"虛擬碼：\n{virtual_code}\n",
        "生成的程式碼必須包含一個 `if __name__ == \"__main__\":` 區塊。\n",
        "這個 `main` 區塊必須：\n"
        "1. 從標準輸入 (stdin) 讀取解決問題所需的所有數據（例如，使用 `input()` 或 `sys.stdin.read()`）。\n"
        "2. 處理這些數據。\n"
        "3. 將最終答案打印 (print) 到標準輸出 (stdout)。\n"
        "4. **不要** 在 `main` 區塊中硬編碼 (hard-code) 任何範例輸入或輸出。\n"
    ]
    all_examples = []
    
    # 1. 加入 AI 生成的測資
    if ai_generated_tests:
        for test_case in ai_generated_tests:
            if isinstance(test_case, (list, tuple)) and len(test_case) == 2:
                # 確保是 (str, str)
                all_examples.append((str(test_case[0]), str(test_case[1])))

    # 2. 加入檔案提供的範例
    if file_examples:
        for ex in file_examples:
            inp = ex.get("input")
            out = ex.get("output")
            if inp is not None and out is not None:
                example_tuple = (str(inp), str(out))
                # 避免重複加入
                if example_tuple not in all_examples:
                    all_examples.append(example_tuple)
    if all_examples: # json_tests is List[List[str, str]]
        code_prompt_lines.append("\n以下是幾個範例，展示了程式執行時**應該**如何處理輸入和輸出（你的程式碼將透過 `stdin` 接收這些輸入）：\n")
        for i, (inp, out) in enumerate(all_examples):
            inp_repr = repr(str(inp)) # 確保是字串
            out_repr = repr(str(out)) # 確保是字串
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
    return "".join(code_prompt_lines)

def build_fix_code_prompt(user_need: str, virtual_code: str, ai_generated_tests: Optional[List[Tuple[str, str]]], history: List[str], current_code: str, modification_request: str,solution: Optional[str] = None,file_examples: Optional[List[Dict[str, str]]] = None) -> str:
    """
    (MODIFIED) 建立一個用於「互動式修改」的提示。
    這會包含歷史紀錄、當前程式碼和修改需求。
    """
    code_prompt_lines = [
        "用繁體中文回答。\n你是程式碼生成助理。\n任務：依據使用者需求、虛擬碼、範例，產生正確可執行的 Python 程式碼，並加上白話註解。\n",
        f"原始需求：\n{user_need}\n",
        f"虛擬碼：\n{virtual_code}\n",
        f"歷史紀錄：\n{' -> '.join(history)}\n",
        f"--- 當前程式碼 (有問題或待修改) ---\n"
        f"```python\n{current_code}\n```\n"
        f"--- !! 新增修改需求 !! ---\n"
        f"{modification_request}\n\n",
        "--- 程式碼要求 (務必遵守) ---\n",
        "生成的程式碼必須包含一個 `if __name__ == \"__main__\":` 區塊。\n",
        "這個 `main` 區塊必須：\n"
        "1. 從標準輸入 (stdin) 讀取解決問題所需的所有數據。\n"
        "2. 處理這些數據。\n"
        "3. 將最終答案打印 (print) 到標準輸出 (stdout)。\n"
        "4. **不要** 在 `main` 區塊中硬編碼 (hard-code) 任何範例輸入或輸出。\n"
    ]

    if solution:
        code_prompt_lines.append("\n--- 參考解法 (僅供參考) ---\n")
        code_prompt_lines.append(f"```python\n{solution}\n```\n")

    all_examples = []

    if ai_generated_tests:
        for test_case in ai_generated_tests:
            if isinstance(test_case, (list, tuple)) and len(test_case) == 2:
                all_examples.append((str(test_case[0]), str(test_case[1])))

    # 2. 加入檔案提供的範例
    if file_examples:
        for ex in file_examples:
            inp = ex.get("input")
            out = ex.get("output")
            if inp is not None and out is not None:
                example_tuple = (str(inp), str(out))
                if example_tuple not in all_examples:
                    all_examples.append(example_tuple)
    if all_examples: # 重新使用先前生成的測資
        code_prompt_lines.append("\n以下是幾個範例，展示了程式執行時**應該**如何處理輸入和輸出（你的程式碼將透過 `stdin` 接收這些輸入）：\n")
        for i, (inp, out) in enumerate(all_examples):
            inp_repr = repr(str(inp))
            out_repr = repr(str(out))
            code_prompt_lines.append(f"--- 範例 {i+1} ---")
            code_prompt_lines.append(f"若 stdin 輸入為: {inp_repr}")
            code_prompt_lines.append(f"則 stdout 輸出應為: {out_repr}")
        code_prompt_lines.append("\n再次強調：你的 `main` 程式碼不應該包含這些範例，它應該是通用的，能從 `stdin` 讀取任何合法的輸入。\n")
    else:
        code_prompt_lines.append("由於沒有提供範例，請確保程式碼結構完整，包含 `if __name__ == \"__main__\":` 區塊並能從 `stdin` 讀取數據。\n")

    code_prompt_lines.append("⚠️ **重要**：請僅輸出一個 Python 程式碼區塊 ```python ... ```，絕對不要輸出任何額外文字或解釋。")
    
    return "".join(code_prompt_lines)