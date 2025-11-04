from core.model_interface import build_explain_prompt, generate_response


def explain_user_code():
    print("=== 程式碼解釋模式 ===")
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
        print("[提示] 沒有輸入程式碼。")
        return

    user_need = input("請輸入需求 (用於解釋背景，可留空): ").strip()
    explain_prompt = build_explain_prompt(user_need, user_code)
    explain_resp = generate_response(explain_prompt)

    print("\n=== 模型回覆 (解釋) ===\n")
    print(explain_resp, "\n")


def get_code_explanation(user_code: str, user_need: str) -> str:
    """
    (重構後的函式)
    
    接收程式碼和可選的需求說明，呼叫 AI 生成解釋。
    這個版本是「純粹的」(pure)，它移除了所有 input() 和 print() 呼叫，
    使其可以被 FastAPI 安全地呼叫。
    
    Args:
        user_code: 使用者提供的 Python 程式碼字串。
        user_need: (可選) 該程式碼的需求或背景說明。

    Returns:
        AI 生成的解釋字串。
    """
    
    # 檢查程式碼是否為空
    if not user_code.strip():
        # 在 API 層級，我們通常會回傳錯誤訊息，
        # 而不是像 CLI 中那樣只提示。
        # 不過，這個檢查也可以交給 API 端點去做。
        return "[提示] 沒有提供程式碼。"

    # --- 核心邏輯 (與您原本的檔案相同) ---
    explain_prompt = build_explain_prompt(user_need, user_code)
    explain_resp = generate_response(explain_prompt)
    # -------------------------------------

    # 回傳結果，而不是 print
    return explain_resp