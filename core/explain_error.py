import subprocess
import tempfile
import os
from core.model_interface import generate_response  # 你的 generate_response 函式

def explain_code_error(user_code: str) -> str:
    """
    嘗試執行使用者程式碼：
    - 若執行成功，回傳成功訊息。
    - 若失敗，將錯誤訊息送給模型：
        1. 解釋錯誤原因（用繁體中文）
        2. 提出修正建議
        3. 給出一個可能正確的範例程式碼
    """
    tmp_path = None
    try:
        # 寫入臨時檔案
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
            tmp.write(user_code)
            tmp_path = tmp.name

        # 嘗試執行
        run = subprocess.run(["python3", tmp_path],
                             input="", # <<--- 修正: 傳入空字串避免 input() 阻塞
                             capture_output=True, text=True, timeout=10)

        if run.returncode == 0:
            return "[成功] 程式碼可以正常執行 ✅"

        # 執行失敗，生成錯誤解釋
        error_msg = run.stderr
        explain_prompt = (
            "你是一個 Python 助教，請幫助使用者理解錯誤。\n"
            "請用繁體中文：\n"
            "1. 解釋錯誤原因\n"
            "2. 給出修正方向（不需立即提供完整程式）\n"
            "3. 用簡單易懂的語言回答\n"
            "\n=== 使用者程式碼 ===\n"
            "```python\n" + user_code + "\n```\n"
            "\n=== 錯誤訊息 ===\n"
            "```\n" + error_msg + "\n```\n"
        )

        explanation = generate_response(explain_prompt)
        print("錯誤解釋如下：\n")
        print(explanation)
        print("\n是否根據這個錯誤嘗試提供修正版程式？(y/n): ", end="")

        choice = input().strip().lower()
        if choice in ["y", "yes", "是", "好"]:
            fix_prompt = (
                "根據以下的程式與錯誤訊息，請嘗試修正錯誤。\n"
                "用繁體中文說明修正邏輯，並給出完整的正確程式碼（放在 ```python 區塊內）。\n"
                "\n=== 使用者程式碼 ===\n"
                "```python\n" + user_code + "\n```\n"
                "\n=== 錯誤訊息 ===\n"
                "```\n" + error_msg + "\n```\n"
            )
            fixed_code = generate_response(fix_prompt)
            return "\n修正版程式：\n\n" + fixed_code
        else:
            return "\n已取消自動修正。若需要，可稍後再請我生成修正版。"

    except Exception as e:
        return f"[錯誤] 無法解釋程式碼: {e}"

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
