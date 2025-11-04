import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Any

from core import (
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
    build_fix_code_prompt,
    generate_response,  
    interactive_chat,
    build_translate_prompt,
    build_suggestion_prompt,
    build_chat_prompt
    # ----------------------------------------------
)



# --- 修正: 根據原始 main.py 的結構, 這些模組應位於 core/ ---
from core.explain_user_code import get_code_explanation 
from core.explain_error import explain_code_error
# ----------------------------------------------------

# --- FastAPI 應用程式實例 ---
app = FastAPI(
    title="Akapychan Code Generator API",
    description="將互動式 CLI 重構為 FastAPI 服務",
    version="1.0.0"
)

# --- Pydantic 資料模型 (用於 API 請求和回應) ---

class NeedRequest(BaseModel):
    user_need: str = Field(..., description="使用者的需求說明")

class VirtualCodeResponse(BaseModel):
    virtual_code: str

class TestGenResponse(BaseModel):
    json_tests: Optional[List[List[Any]]]
    raw_response: str

class GenerateCodeRequest(BaseModel):
    user_need: str
    virtual_code: str
    ai_generated_tests: Optional[List[List[Any]]] = None

class GeneratedCodeResponse(BaseModel):
    code: Optional[str]
    explanation: Optional[str]
    raw_response: str

class ValidateCodeRequest(BaseModel):
    code: str
    json_tests: List[List[Any]] = Field(..., description="要執行的測資列表，格式為 [[input, output], ...]")

class ValidationResultItem(BaseModel):
    case: str
    input: Optional[str]
    expected_output: Optional[str]
    actual_output: str
    success: bool
    details: str

class ValidateCodeResponse(BaseModel):
    all_passed: bool
    results: List[ValidationResultItem]

class FixCodeRequest(BaseModel):
    user_need: str
    virtual_code: str
    current_code: str
    modification_request: str
    ai_generated_tests: Optional[List[List[Any]]] = None
    history: Optional[List[str]] = None

class FixCodeResponse(BaseModel):
    new_code: Optional[str]
    raw_response: str

class ValidateUserCodeRequest(BaseModel):
    user_code: str
    user_need: Optional[str] = Field(None, description="用以生成測資的需求說明 (若留空，則僅執行一次)")

class ValidateUserCodeResponse(BaseModel):
    all_passed: bool
    tests_generated: bool
    json_tests: Optional[List[List[Any]]]
    results: List[ValidationResultItem]
    error_analysis: Optional[str] = None

class ExplainCodeRequest(BaseModel):
    code: str
    user_need: str = Field(..., description="程式碼的原始需求")

class ExplainCodeResponse(BaseModel):
    explanation: str
    raw_response: str

# --- 補全功能: 模式 5 (翻譯) ---
class TranslateRequest(BaseModel):
    text_to_translate: str
    target_language: str = Field("English", description="目標語言")
    source_language: Optional[str] = Field(None, description="來源語言 (可選, 讓 AI 自行偵測)")

class TranslateResponse(BaseModel):
    translated_text: str
    raw_response: str
# --------------------------------

# --- 補全功能: 模式 6 (程式碼建議) ---
class SuggestRequest(BaseModel):
    code: str
    user_need: Optional[str] = Field(None, description="相關的需求說明 (可選)")

class SuggestResponse(BaseModel):
    suggestions: str # 建議通常是文字
    raw_response: str
# ----------------------------------

# --- 補全功能: 預設 (聊天) ---
class ChatRequest(BaseModel):
    prompt: str
    history: Optional[List[dict]] = Field(None, description="聊天歷史 (可選), e.g., [{'role': 'user', 'content': '...'}, ...]")

class ChatResponse(BaseModel):
    response: str
    raw_response: str
# -----------------------------




@app.post("/mode1/generate_virtual_code", 
          response_model=VirtualCodeResponse, 
          tags=["Mode 1: Code Generation"])
async def api_generate_virtual_code(request: NeedRequest):
    """
    (Mode 1, 步驟 1) 根據使用者需求生成虛擬碼。
    """
    vc_prompt = build_virtual_code_prompt(request.user_need)
    vc_resp = generate_response(vc_prompt)
    return {"virtual_code": vc_resp}

@app.post("/mode1/generate_tests", 
          response_model=TestGenResponse, 
          tags=["Mode 1: Code Generation"])
async def api_generate_tests(request: NeedRequest):
    """
    (Mode 1, 步驟 2) 根據使用者需求生成測資。
    """
    test_prompt = build_test_prompt(request.user_need)
    test_resp = generate_response(test_prompt)
    json_tests = extract_json_block(test_resp) or parse_tests_from_text(request.user_need)
    return {"json_tests": json_tests, "raw_response": test_resp}

@app.post("/mode1/generate_code", 
          response_model=GeneratedCodeResponse, 
          tags=["Mode 1: Code Generation"])
async def api_generate_code(request: GenerateCodeRequest):
    """
    (Mode 1, 步驟 3) 根據需求、虛擬碼和測資生成程式碼及解釋。
    """
    code_prompt_string = build_stdin_code_prompt(
        request.user_need, 
        request.virtual_code, 
        ai_generated_tests=request.ai_generated_tests
    )
    code_resp = generate_response(code_prompt_string) 

    code_or_list = extract_code_block(code_resp)
    if isinstance(code_or_list, list) and code_or_list:
        code = code_or_list[0]
    elif isinstance(code_or_list, str):
        code = code_or_list
    else:
        code = None 

    explanation = None
    if code:
        explain_prompt = build_explain_prompt(request.user_need, code)
        explanation = generate_response(explain_prompt)
        
    return {
        "code": code, 
        "explanation": explanation,
        "raw_response": code_resp
    }

@app.post("/mode1/validate_code", 
          response_model=ValidateCodeResponse, 
          tags=["Mode 1: Code Generation", "Validation"])
async def api_validate_code(request: ValidateCodeRequest):
    """
    (Mode 1, 步驟 4) 驗證生成的程式碼 (或任何程式碼) 是否通過指定的測資。
    """
    all_passed = True
    results: List[ValidationResultItem] = []
    
    if not request.json_tests:
        success, output_msg = validate_main_function(request.code, stdin_input=None, expected_output=None)
        results.append(ValidationResultItem(
            case="default (no input)",
            input=None,
            expected_output=None,
            actual_output=output_msg,
            success=success,
            details=output_msg
        ))
        all_passed = success
    else:
        for i, test in enumerate(request.json_tests):
            if not (isinstance(test, list) and len(test) == 2):
                results.append(ValidationResultItem(
                    case=f"Test Case {i+1} (Skipped)",
                    input=repr(test),
                    expected_output=None,
                    actual_output="",
                    success=False,
                    details=f"Invalid test format: {repr(test)}"
                ))
                all_passed = False
                continue

            test_input_val = test[0]
            test_output_val = test[1]
            test_input_str = str(test_input_val) if test_input_val is not None else None
            test_output_str = str(test_output_val) if test_output_val is not None else None

            success, output_msg = validate_main_function(
                code=request.code,
                stdin_input=test_input_str,
                expected_output=test_output_str
            )
            
            # validate_main_function 回傳 (success, output_or_error)
            # 我們需要解析 output_or_error 來取得 "Actual Output"
            actual_output = output_msg
            if not success:
                # 嘗試從錯誤訊息中解析實際輸出
                if "Actual Output:" in output_msg:
                    try:
                        actual_output = output_msg.split("Actual Output:")[1].split("\n")[0].strip()
                    except Exception:
                        pass # 保持 output_msg 為完整錯誤
            else:
                # 如果成功，output_msg 就是 STDOUT
                actual_output = output_msg.strip()


            results.append(ValidationResultItem(
                case=f"Test Case {i+1}",
                input=repr(test_input_val),
                expected_output=repr(test_output_val),
                actual_output=actual_output,
                success=success,
                details=output_msg
            ))
            if not success:
                all_passed = False

    return {"all_passed": all_passed, "results": results}


@app.post("/mode1/fix_code", 
          response_model=FixCodeResponse, 
          tags=["Mode 1: Code Generation"])
async def api_fix_code(request: FixCodeRequest):
    """
    (Mode 1, 步驟 5) 根據新的修改需求，修正現有的程式碼。
    """
    fix_prompt_string = build_fix_code_prompt(
        user_need=request.user_need, 
        virtual_code=request.virtual_code, 
        ai_generated_tests=request.ai_generated_tests,
        history=request.history or [], 
        current_code=request.current_code, 
        modification_request=request.modification_request
    )
    
    fix_resp = generate_response(fix_prompt_string)
    
    new_code_or_list = extract_code_block(fix_resp)
    if isinstance(new_code_or_list, list) and new_code_or_list:
        new_code = new_code_or_list[0]
    elif isinstance(new_code_or_list, str):
        new_code = new_code_or_list
    else:
        new_code = None

    return {"new_code": new_code, "raw_response": fix_resp}




@app.post("/mode3/validate_user_code", 
          response_model=ValidateUserCodeResponse, 
          tags=["Mode 3: Validate User Code"])
async def api_validate_user_code(request: ValidateUserCodeRequest):
    """
    (Mode 3) 驗證使用者提供的程式碼。
    如果提供了 user_need，將嘗試生成測資來進行驗證。
    如果驗證失敗，將嘗試分析錯誤。
    """
    user_code = request.user_code
    user_need = request.user_need
    json_tests = []
    all_passed = True
    error_analysis = None
    results: List[ValidationResultItem] = []
    
    # 步驟 1: 如果有需求，生成測資
    if user_need:
        test_prompt = build_test_prompt(user_need)
        test_resp = generate_response(test_prompt)
        json_tests = extract_json_block(test_resp) or parse_tests_from_text(user_need)
        tests_generated = bool(json_tests)
    else:
        tests_generated = False

    # 步驟 2: 執行驗證
    if json_tests:
        # (A) 使用 AI 生成的測資進行驗證
        for i, test in enumerate(json_tests):
            if not (isinstance(test, list) and len(test) == 2):
                results.append(ValidationResultItem(
                    case=f"Test Case {i+1} (Skipped)",
                    input=repr(test),
                    expected_output=None,
                    actual_output="",
                    success=False,
                    details=f"Invalid test format: {repr(test)}"
                ))
                all_passed = False
                continue
            
            test_input_val = test[0]
            test_output_val = test[1]
            test_input_str = str(test_input_val) if test_input_val is not None else ""
            test_output_str = str(test_output_val) if test_output_val is not None else None

            success, output_msg = validate_main_function(
                code=user_code,
                stdin_input=test_input_str,
                expected_output=test_output_str
            )
            
            actual_output = output_msg # 預設
            if not success:
                if "Actual Output:" in output_msg:
                    try:
                        actual_output = output_msg.split("Actual Output:")[1].split("\n")[0].strip()
                    except Exception:
                        pass
            else:
                actual_output = output_msg.strip()
                
            results.append(ValidationResultItem(
                case=f"Test Case {i+1}",
                input=repr(test_input_val),
                expected_output=repr(test_output_val),
                actual_output=actual_output,
                success=success,
                details=output_msg
            ))
            if not success:
                all_passed = False
    else:
        # (B) 僅執行一次 (無輸入)
        success, output_msg = validate_main_function(user_code, stdin_input=None, expected_output=None)
        results.append(ValidationResultItem(
            case="default (no input)",
            input=None,
            expected_output=None,
            actual_output=output_msg.strip() if success else output_msg,
            success=success,
            details=output_msg
        ))
        all_passed = success

    # 步驟 3: 如果失敗，分析錯誤
    if not all_passed:
        try:
            error_analysis = explain_code_error(user_code) 
        except Exception as e:
            error_analysis = f"[分析失敗] {e}"

    return {
        "all_passed": all_passed,
        "tests_generated": tests_generated,
        "json_tests": json_tests,
        "results": results,
        "error_analysis": error_analysis
    }


@app.post("/mode4/explain_code", 
          response_model=ExplainCodeResponse, 
          tags=["Mode 4: Explain Code"])
async def api_explain_code(request: ExplainCodeRequest):
    """
    (Mode 4) 產生程式碼的解釋。
    這個端點會呼叫重構後的 `get_code_explanation` 函式。
    """
    try:
        # --- (新) 呼叫重構後的 "純" 函式 ---
        explanation = get_code_explanation(
            user_code=request.code, 
            user_need=request.user_need
        )
        
        # -------------------------------------
        
        return {"explanation": explanation, "raw_response": explanation}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate explanation: {e}")



@app.post("/mode5/translate", 
            response_model=TranslateResponse, 
            tags=["Mode 5: Translate"])
async def api_translate(request: TranslateRequest):
    """
    (Mode 5) 翻譯指定的文字。
    """
    try:
        prompt = build_translate_prompt(
            text=request.text_to_translate,
            target_language=request.target_language
        )
        # --------------------------------------------------------
        
        resp = generate_response(prompt)
        return {"translated_text": resp, "raw_response": resp}
    
    except NameError:
         raise HTTPException(status_code=501, detail="`build_translate_prompt` is not implemented in core.model_interface.")
    except TypeError as e:
         # 捕捉任何剩餘的參數錯誤
         raise HTTPException(status_code=500, detail=f"Failed to call build_translate_prompt: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {e}")


@app.post("/mode6/suggest_code", 
            response_model=SuggestResponse, 
            tags=["Mode 6: Code Suggestions"])
async def api_get_code_suggestions(request: SuggestRequest):
    """
    (Mode 6) 根據現有程式碼提供建議。
    """
    try:
        # --- 修正: 參數應為 'user_code' (來自 model_interface.py) ---
        prompt = build_suggestion_prompt(
            user_code=request.code, # 函數參數: model欄位
            user_need=request.user_need
        )
        # -----------------------------------------
        
        resp = generate_response(prompt)
        return {"suggestions": resp, "raw_response": resp}
    except NameError:
         raise HTTPException(status_code=501, detail="`build_suggestion_prompt` is not implemented in core.model_interface.")
    except Exception as e:
        if isinstance(e, TypeError):
             raise HTTPException(status_code=500, detail=f"Failed to call build_suggestion_prompt: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get suggestions: {e}")
# ================================================
# 預設: 聊天 - 補全
# ================================================

@app.post("/chat", 
            response_model=ChatResponse, 
            tags=["Chat"])
async def api_chat(request: ChatRequest):
    """
    (Default) 執行通用的聊天。
    (修正: 整合 interactive_chat 的邏輯，使其能判斷程式碼或一般問題)
    """
    try:
        user_input = request.prompt
        prompt_string = ""
        
        # --- 邏輯移植 ---
        # 偵測是否貼了 Python 程式碼 (邏輯來自 interactive_chat)
        if "def " in user_input or "print(" in user_input or "for " in user_input:
            # 1. 如果是程式碼，呼叫「解釋」
            print("\n[API Chat] 偵測到 Python 程式碼，進入解釋模式...\n")
            # 呼叫解釋程式碼的 prompt
            prompt_string = build_explain_prompt("使用者貼上的程式碼", user_input)
        else:
            # 2. 如果是純文字，呼叫「聊天」
            print("\n[API Chat] 進入一般聊天模式...\n")
            # 呼叫一般的聊天 prompt (這個函式應能處理 history)
            prompt_string = build_chat_prompt(
                prompt=request.prompt,
                history=request.history
            )
        # ----------------

        resp = generate_response(prompt_string)
        return {"response": resp, "raw_response": resp}
    
    except NameError as e:
         # 確保 main.py 頂部已 import build_explain_prompt 和 build_chat_prompt
         raise HTTPException(status_code=501, detail=f"核心函式未實現 (請檢查 import): {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")

# --- 啟動伺服器 ---

if __name__ == "__main__":
    """
    使用 uvicorn 啟動伺服器。
    在終端機中執行: python main.py
    
    或者，使用 uvicorn CLI (推薦用於開發):
    uvicorn main:app --reload
    """
    uvicorn.run(app, host="0.0.0.0", port=8000)