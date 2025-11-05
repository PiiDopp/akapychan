import os
import subprocess
import sys
import tempfile
import shutil
import importlib.util
import time
import typing  

from core.data_structures import auto_convert_input, auto_convert_output

# ... (檔案中其他的函式，例如 call_function_safely 保持不變) ...


# ---
# === 函式 1：validate_python_code (使用 Pytest) ===
# (此函式來自上一個請求，保持不變)
# ---
def validate_python_code(code: str, 
                         tests: list[tuple], 
                         user_need: str = "") -> tuple[bool, str]:
    """
    使用 subprocess 和 pytest 獨立執行緒驗證程式碼。
    這比 importlib 更安全，因為程式碼在隔離的 process 中執行。

    Args:
        code: 要驗證的 Python 程式碼字串 (將存為 solution.py)。
        tests: 測資列表 [(func_name, args, expected_result), ...]
        user_need: (未使用，但保留簽章一致性)
                     
    Returns:
        (bool, output_str): (是否成功, pytest 的 stdout/stderr 輸出或錯誤訊息)
    """
    tmp_dir = None
    try:
        # 1. 建立臨時資料夾
        tmp_dir = tempfile.mkdtemp()
        
        # 2. 將使用者程式碼寫入 solution.py
        solution_path = os.path.join(tmp_dir, "solution.py")
        with open(solution_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 3. 處理測資
        if not tests:
            # 如果沒有提供測資，至少檢查程式碼是否能被 python3 基礎執行 (無 input)
            run_check = subprocess.run(
                ["python3", solution_path],
                input="", capture_output=True, text=True, timeout=10,
                cwd=tmp_dir
            )
            
            if run_check.returncode == 0 or "EOFError" in run_check.stderr:
                return True, "[Validation] Code executed successfully (no tests provided)."
            else:
                err_msg = run_check.stderr.strip() if run_check.stderr.strip() else run_check.stdout.strip()
                return False, f"[Validation Error] Code failed to execute.\n{err_msg}"

        # --- 如果有測資，動態產生 pytest 檔案 ---
        
        func_names = sorted(list(set([t[0] for t in tests])))
        
        test_content = "import pytest\n"
        test_content += "import sys\n"
        test_content += "import os\n"
        test_content += "sys.path.append(os.path.dirname(__file__))\n\n"
        
        try:
            test_content += f"from solution import {', '.join(func_names)}\n\n"
        except ImportError as ie:
            return False, f"[Validation Error] Failed to import functions from code: {ie}"

        for i, (func_name, args, expected) in enumerate(tests):
            args_repr = ", ".join(map(repr, args))
            expected_repr = repr(expected)
            
            test_content += f"def test_case_{i}():\n"
            test_content += f"    # Test: {func_name}({args_repr}) == {expected_repr}\n"
            test_content += f"    actual = {func_name}({args_repr})\n"
            test_content += f"    assert actual == {expected_repr}\n\n"

        # 4. 將產生的測試內容寫入檔案
        test_path = os.path.join(tmp_dir, "test_generated.py")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_content)

        # 5. 在 subprocess 中執行 pytest
        run = subprocess.run(
            ["python3", "-m", "pytest", test_path, "-v", "--tb=short"],
            cwd=tmp_dir,
            capture_output=True, 
            text=True, 
            timeout=15
        )

        # 6. 檢查 Pytest 的 exit code
        output = run.stdout + "\n" + run.stderr
        
        if run.returncode == 0:
            return True, output
        else:
            return False, output

    except subprocess.TimeoutExpired:
        return False, "[Validation Error] Pytest execution timed out (15s)."
    except Exception as e:
        return False, f"[Validation Error] An unexpected error occurred: {e}"
    finally:
        # 7. 清理臨時資料夾
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---
# === 函式 2：_normalize_output ===
# (此函式保持不變，validate_main_function 依賴它)
# ---
def _normalize_output(s: str) -> str:
    """
    輔助函數：將 stdout 和 expected output 字串標準化以便進行比較。
    """
    if not isinstance(s, str):
        return str(s)

    s = s.strip()

    if len(s) >= 2:
        if s.startswith("'") and s.endswith("'"):
            s = s[1:-1]
        elif s.startswith('"') and s.endswith('"'):
            s = s[1:-1]

    s = s.replace("'", '"')
    s = s.replace(" ", "")

    return s


# ---
# === 函式 3：validate_main_function (重點修改) ===
# (改為使用 tmp_dir，與 validate_python_code 保持一致)
# ---
def validate_main_function(code: str, 
                         stdin_input: str = None, 
                         expected_output: str = None) -> tuple[bool, str]:
    """
    測試程式碼是否可執行 (透過 __main__ 區塊)。
    (第 3 版修改：改用臨時資料夾，統一環境管理)
    
    Args:
        code: 要驗證的 Python 程式碼字串。
        stdin_input: (重要) 要傳遞給 subprocess 的標準輸入 (stdin)。
        expected_output: (可選) 期望的標準輸出 (stdout)。
                         
    Returns:
        (bool, output_str): (是否成功, 實際的 stdout 或 stderr 訊息)
    """
    tmp_dir = None # <--- 修改點
    try:
        # 1. 建立臨時資料夾
        tmp_dir = tempfile.mkdtemp()
        
        # 2. 建立臨時檔案
        tmp_path = os.path.join(tmp_dir, "main_script.py") # <--- 修改點
        with open(tmp_path, "w", encoding="utf-8") as tmp: # <--- 修改點
            tmp.write(code)

        # 3. 決定要傳入的 input
        input_data = stdin_input if stdin_input is not None else ""
        
        # 4. 執行 subprocess
        run = subprocess.run(
            ["python3", tmp_path],
            input=input_data,
            capture_output=True, 
            text=True, 
            timeout=10,
            cwd=tmp_dir # <--- 新增點 (在臨時目錄中執行)
        )
        
        actual_output = run.stdout.strip()
        
        if run.returncode == 0:
            # 執行成功 (Return Code 0)
            
            if expected_output is not None:
                # 如果有提供「期望輸出」，使用 _normalize_output 進行比對
                
                normalized_actual = _normalize_output(actual_output)
                normalized_expected = _normalize_output(expected_output)
                
                if normalized_actual == normalized_expected:
                    # 驗證成功 (正規化後匹配)
                    return True, actual_output # 回傳原始的(stripped)輸出
                else:
                    # 輸出不匹配
                    err_msg = (
                        f"Actual Output:\n{actual_output}\n\n"
                        f"[Output Mismatch (Normalized)]\n"
                        f"Expected: {repr(normalized_expected)}\n"
                        f"Got:      {repr(normalized_actual)}"
                    )
                    return False, err_msg
            else:
                # 沒有提供「期望輸出」，只要執行成功就算通過
                return True, actual_output
        else:
            # 執行失敗 (Return Code != 0)
            output_on_fail = run.stderr.strip() if run.stderr.strip() else run.stdout.strip()
            return False, output_on_fail

    except subprocess.TimeoutExpired:
        return False, "[Validation Error] Code execution timed out (10s)."
    except Exception as e:
        return False, f"[Validation Error] An unexpected error occurred: {e}"
    finally:
        # 5. 清理臨時資料夾
        if tmp_dir and os.path.exists(tmp_dir): # <--- 修改點
            shutil.rmtree(tmp_dir, ignore_errors=True) # <--- 修改點