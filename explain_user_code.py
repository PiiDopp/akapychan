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
