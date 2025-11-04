import tkinter as tk
from tkinter import scrolledtext, font
import threading
import queue
import os
import json
import random
import re  # 

# 從你現有的專案中導入所有需要的函式
# 確保 main.py, core, quiz 等都在 Python 的路徑中
from core import ask_input, generate_response, \
                 extract_code_block, extract_json_block, parse_tests_from_text, normalize_tests, \
                 validate_python_code, generate_tests, validate_main_function
from core.model_interface import build_virtual_code_prompt, build_test_prompt, build_explain_prompt, build_code_prompt, call_ollama_cli, MODEL_NAME, interactive_chat, interactive_langchain_chat, interactive_code_modification_loop, build_stdin_code_prompt, build_fix_code_prompt, interactive_translate, get_code_suggestions, build_suggestion_prompt, build_translate_prompt
from quiz.quiz_mode import quiz_mode
from core.explain_user_code import explain_user_code
from core.explain_error import explain_code_error

# --- 模式 2 (Quiz) 所需的額外導入 ---
# 從 core.data_structures 導入 LeetCode 輔助工具
try:
    from core.data_structures import ListNode, TreeNode, list_to_nodes, nodes_to_list, list_to_tree, tree_to_list, auto_convert_input, auto_convert_output
except ImportError:
    print("[錯誤] 無法從 core.data_structures 導入 LeetCode 輔助類別。模式 2 可能會失敗。")
    # 定義備用 (fallback) 類別，以防導入失敗
    class ListNode: pass
    class TreeNode: pass
    def auto_convert_output(result): return result

# --- 模式 2 (Quiz) 所需的輔助函式 (從 quiz_mode.py 移植) ---

def _normalize_output(s: str) -> str:
    """
    (來自 quiz_mode.py)
    輔助函數：將 stdout 和 expected output 字串標準化以便進行比較。
    """
    if not isinstance(s, str):
        if s is None:
            return "null"
        if isinstance(s, bool):
            return str(s).lower()
        s = str(s)
    s = s.strip()
    if len(s) >= 2:
        if s.startswith("'") and s.endswith("'"):
            s = s[1:-1]
        elif s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
    s = s.replace("'", '"')
    s = s.replace(" ", "")
    return s

def get_data_structures_preamble() -> str:
    """
    (來自 quiz_mode.py)
    返回 LeetCode 題目測試可能需要的輔助類別和函式字串。
    """
    return """
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right
def list_to_nodes(lst):
    dummy = ListNode()
    curr = dummy
    for val in lst:
        curr.next = ListNode(val)
        curr = curr.next
    return dummy.next
def nodes_to_list(node):
    result = []
    while node:
        result.append(node.val)
        node = node.next
    return result
def list_to_tree(lst):
    if not lst:
        return None
    nodes = [TreeNode(val) if val is not None else None for val in lst]
    kids = nodes[::-1]
    root = kids.pop()
    for node in nodes:
        if node:
            if kids: node.left = kids.pop()
            if kids: node.right = kids.pop()
    return root
def tree_to_list(root):
    if not root:
        return []
    result, queue = [], [root]
    while queue:
        node = queue.pop(0)
        if node:
            result.append(node.val)
            queue.append(node.left)
            queue.append(node.right)
        else:
            result.append(None)
    while result and result[-1] is None:
        result.pop()
    return result
def auto_convert_output(result):
    if isinstance(result, ListNode):
        return nodes_to_list(result)
    if isinstance(result, TreeNode):
        return tree_to_list(result)
    return result
"""

def parse_leetcode_info(solution_str: str, input_str: str) -> tuple[str | None, list[str], str]:
    """
    (來自 quiz_mode.py)
    解析 LeetCode 格式的 solution 和 input。
    """
    match = re.search(r"def (\w+)\(self, ([^\)]+)\)", solution_str)
    if not match:
        if "def __init__(self" in solution_str:
            return None, [], ""
        match = re.search(r"def (\w+)\(self, ([^\)]+)\) ->", solution_str)
        if not match:
             return None, [], ""
    func_name = match.group(1)
    args_str = match.group(2)
    arg_names = [arg.split(':')[0].strip() for arg in args_str.split(',')]
    try:
        input_definitions = input_str
        raw_arg_names = re.findall(r"(\w+)\s*=", input_str)
        if set(raw_arg_names) == set(arg_names):
             return func_name, arg_names, input_definitions
        else:
             if not raw_arg_names and not arg_names:
                 return None, [], ""
             if not raw_arg_names: 
                 return None, [], "" 
             return func_name, raw_arg_names, input_definitions
    except Exception as e:
        print(f"[警告] LeetCode input 解析失敗: {e}")
        return None, [], ""

def list_obj_units(obj_root="data"):
    """(來自 quiz_mode.py)"""
    try:
        return sorted([d for d in os.listdir(obj_root) if os.path.isdir(os.path.join(obj_root, d))])
    except FileNotFoundError:
        print(f"[錯誤] 找不到 'data' 資料夾。")
        return []

def load_all_coding_practice(obj_root="data", unit=None):
    """(來自 quiz_mode.py)"""
    practice_list = []
    search_path = os.path.join(obj_root, unit) if unit else obj_root
    if not os.path.exists(search_path):
        print(f"[警告] 路徑不存在: {search_path}")
        return []
    for root, dirs, files in os.walk(search_path):
        for file in files:
            if file.endswith(".json"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "coding_practice" in data:
                            for item in data["coding_practice"]:
                                item["source_file"] = path 
                                practice_list.append(item)
                except Exception as e:
                    print(f"[讀取失敗] {path}: {e}")
    return practice_list

# --- (輔助函式結束) ---


class ChatApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("Akapychan GUI (Python Code Generator)")
        self.root.geometry("1000x750")

        # --- 狀態變數 ---
        self.current_task = None  # 用於儲存當前的 generator 任務
        self.session_data = {}    # 用於儲存跨步驟的資料 (如 user_need, code)
        self.ui_queue = queue.Queue() # 執行緒安全的消息隊列

        # --- 1. 模式選擇框架 ---
        self_font = font.Font(family="Helvetica", size=10)
        self.mode_frame = tk.Frame(root, pady=5)
        self.mode_frame.pack(fill=tk.X)

        modes = [
            ("1: 生成程式碼", "1"),
            ("2: 出題", "2"),
            ("3: 驗證程式碼", "3"),
            ("4: 程式碼解釋", "4"),
            ("5: 翻譯", "5"),
            ("6: 程式碼建議", "6"),
            ("其他: 聊天", "chat")
        ]
        
        for text, mode in modes:
            btn = tk.Button(self.mode_frame, text=text, font=self_font, 
                            command=lambda m=mode: self.set_mode(m))
            btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        # --- 2. 對話顯示區域 ---
        self.chat_area = scrolledtext.ScrolledText(root, state='disabled', wrap=tk.WORD, 
                                                   height=25, font=("Helvetica", 11))
        self.chat_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        # 設定文字顏色標籤
        self.chat_area.tag_config('user', foreground="#003399") # 
        self.chat_area.tag_config('ai', foreground="#006400")
        self.chat_area.tag_config('system', foreground="#555555", font=("Helvetica", 11, "italic"))
        self.chat_area.tag_config('error', foreground="#CC0000", font=("Helvetica", 11, "bold"))
        self.chat_area.tag_config('code', foreground="#333333", background="#f0f0f0", 
                                  font=("Courier New", 10), 
                                  borderwidth=1, relief="solid", 
                                  lmargin1=10, lmargin2=10, rmargin=10)


        # --- 3. 使用者輸入框架 ---
        self.input_frame = tk.Frame(root, pady=10)
        self.input_frame.pack(fill=tk.X, padx=10)
        
        # 使用 tk.Text 實現多行輸入
        self.input_area = tk.Text(self.input_frame, height=5, font=("Helvetica", 11))
        self.input_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.send_button = tk.Button(self.input_frame, text="送出", 
                                     font=self_font, width=10, 
                                     command=self.process_input)
        self.send_button.pack(side=tk.RIGHT, padx=5, fill=tk.BOTH)

        # 綁定 Enter 鍵 (Shift+Enter 換行)
        self.input_area.bind("<Return>", self.on_enter_key)
        self.input_area.bind("<Shift-Return>", self.on_shift_enter_key)
        
        # --- 啟動 UI 更新迴圈 ---
        self.root.after(100, self.process_ui_queue)

        self.add_to_chat("=== 歡迎使用 Akapychan ===\n請從上方選擇一個模式。", 'system')

    def on_enter_key(self, event):
        """按下 Enter 鍵時送出訊息"""
        self.process_input()
        return "break" # 阻止 Enter 鍵的默認換行行為

    def on_shift_enter_key(self, event):
        """按下 Shift+Enter 鍵時換行"""
        self.input_area.insert(tk.END, "\n")
        return "break"

    def process_ui_queue(self):
        """處理來自背景執行緒的 UI 更新請求"""
        try:
            while not self.ui_queue.empty():
                message, tag = self.ui_queue.get_nowait()
                self._add_to_chat(message, tag)
        finally:
            self.root.after(100, self.process_ui_queue)

    def add_to_chat(self, message, tag=None):
        """
        [執行緒安全] 將訊息放入隊列，以便主執行緒更新 UI
        """
        if "```python" in message:
             parts = message.split("```python")
             self.ui_queue.put((parts[0], tag))
             for part in parts[1:]:
                 if "\n```" in part:
                     code, rest = part.split("\n```", 1)
                     self.ui_queue.put((f"```python{code}\n```", 'code'))
                     if rest.strip():
                         self.ui_queue.put((rest, tag))
                 else:
                     self.ui_queue.put((f"```python{part}", 'code')) # 
        else:
             self.ui_queue.put((message, tag))


    def _add_to_chat(self, message, tag=None):
        """[非執行緒安全] 實際更新 GUI 的內部函式"""
        self.chat_area.config(state='normal')
        if tag:
             if tag == 'code':
                 # 為程式碼區塊前後添加換行以保證間距
                 self.chat_area.insert(tk.END, f"\n{message.strip()}\n\n", (tag,))
             else:
                 self.chat_area.insert(tk.END, f"{message}\n\n", (tag,))
        else:
            self.chat_area.insert(tk.END, f"{message}\n\n")
        self.chat_area.config(state='disabled')
        self.chat_area.see(tk.END) # 捲動到底部

    def set_mode(self, mode):
        """
        設定新模式，取消舊任務，並啟動新任務的 generator
        """
        if self.current_task:
            # 這裡我們不能輕易 "停止" 一個執行緒，
            # 但我們可以透過重置 self.current_task 來 "遺棄" 它。
            # 該執行緒完成後會自行退出。
            self.add_to_chat("[系統] 已取消先前任務。", 'system')
            
        self.current_task = None
        self.session_data = {} # 重置 session

        if mode == "1":
            self.current_task = self.mode1_flow()
        elif mode == "3":
            self.current_task = self.mode3_flow()
        # --- (*** 已補全 ***) ---
        elif mode == "2":
            self.current_task = self.mode2_flow_quiz()
        elif mode == "4":
            self.current_task = self.mode4_flow_explain()
        elif mode == "5":
            self.current_task = self.mode5_flow_translate()
        elif mode == "6":
            self.current_task = self.mode6_flow_suggestions()
        elif mode == "chat":
            self.current_task = self.chat_flow()
        # --- (*** 補全結束 ***) ---
        
        if self.current_task:
            # 啟動任務的第一步 (在執行緒中)
            self.run_threaded(lambda: next(self.current_task))

    def process_input(self, event=None):
        """
        處理使用者的 "送出" 動作
        """
        user_input = self.input_area.get("1.0", tk.END).strip()
        if not user_input:
            return

        self.input_area.delete("1.0", tk.END)
        self.add_to_chat(f"使用者: {user_input}", 'user')

        if self.current_task:
            # 將使用者的輸入發送到當前任務的 generator 中
            self.run_threaded(lambda: self.current_task.send(user_input))
        else:
            self.add_to_chat("[系統] 錯誤：請先從上方選擇一個模式。", 'error')
    
    def run_threaded(self, target_func):
        """
        在背景執行緒中執行目標函式
        """
        thread = threading.Thread(target=self.thread_wrapper, args=(target_func,))
        thread.daemon = True # 確保主程式退出時執行緒也會退出
        thread.start()

    def thread_wrapper(self, target_func):
        """
        執行緒的包裝函式，用於捕獲異常和 StopIteration
        """
        try:
            target_func()
        except StopIteration:
            # Generator 正常結束
            self.add_to_chat("[系統] 任務已完成。您可以選擇一個新模式。", 'system')
            self.current_task = None
        except Exception as e:
            # 捕獲執行緒中的異常
            error_msg = f"[執行緒錯誤] {type(e).__name__}: {e}"
            print(error_msg) # 也在終端機中印出詳細錯誤
            import traceback
            traceback.print_exc()
            self.add_to_chat(error_msg, 'error')
            self.current_task = None # 出錯時終止任務

    # --- 模式 1: 生成程式碼 (完整流程) ---
    def mode1_flow(self):
        """模式 1 的完整流程 (作為 Generator)"""
        
        # 步驟 0: 獲取需求
        self.add_to_chat("[系統] 進入模式 1: 生成程式碼。\n請在下方輸入您的需求說明，然後按 '送出'。", 'system')
        user_need = yield  # 暫停，等待 process_input().send()
        
        self.session_data = {
            'user_need': user_need, 
            'history': [f"初始需求: {user_need}"]
        }

        # 步驟 1: 生成虛擬碼
        while True:
            self.add_to_chat("[系統] 正在生成虛擬碼...", 'system')
            
            # (!!!) 耗時操作
            vc_prompt = build_virtual_code_prompt(self.session_data['user_need'])
            vc_resp = generate_response(vc_prompt) 
            
            self.add_to_chat(f"=== 模型回覆 (虛擬碼) ===\n{vc_resp}", 'ai')
            
            self.add_to_chat("是否符合需求？(y: 繼續, n: 重新生成, a: 新增補充說明)", 'system')
            confirm = (yield).strip().lower() # 暫停，等待 y/n/a
            
            if confirm in ("", "y", "yes"):
                self.session_data['virtual_code'] = vc_resp
                break # 進入下一步
            elif confirm in ("n", "no"):
                self.add_to_chat("[系統] 重新生成虛擬碼...\n", 'system')
                continue # 迴圈重新開始
            elif confirm == "a":
                self.add_to_chat("請輸入補充說明：", 'system')
                extra_info = (yield).strip() # 暫停，等待補充說明
                if extra_info:
                    self.session_data['user_need'] += f"\n(補充說明: {extra_info})"
                    self.session_data['history'].append(f"補充: {extra_info}")
                self.add_to_chat("[系統] 已加入補充說明，重新生成虛擬碼...\n", 'system')
                continue
            else:
                self.add_to_chat("[提示] 無效輸入，請輸入 y/n/a。", 'error')
                # 迴圈會自動再次詢問

        # 步驟 2: 生成測資
        self.add_to_chat("\n[提示] 正在生成測資...\n", 'system')
        
        # (!!!) 耗時操作
        test_prompt = build_test_prompt(self.session_data['user_need'])
        test_resp = generate_response(test_prompt)
        
        self.add_to_chat(f"\n=== 模型回覆 (測資) ===\n{test_resp}\n", 'ai')

        json_tests = extract_json_block(test_resp) or parse_tests_from_text(test_resp)
        self.session_data['json_tests'] = json_tests

        if json_tests:
            self.add_to_chat(f"[提示] 已成功提取 {len(json_tests)} 筆測資。", 'system')
        else:
            self.add_to_chat("[警告] 未能從模型回覆中提取 JSON 測資。", 'error')

        # 步驟 3: 生成程式碼
        self.add_to_chat("\n[提示] 正在根據虛擬碼和測資生成 (stdin/stdout) 程式碼...", 'system')
        
        # (!!!) 耗時操作
        code_prompt_string = build_stdin_code_prompt(
            self.session_data['user_need'], 
            self.session_data['virtual_code'], 
            ai_generated_tests=json_tests 
        )
        code_resp = generate_response(code_prompt_string) 

        code_or_list = extract_code_block(code_resp)
        if isinstance(code_or_list, list) and code_or_list:
            code = code_or_list[0]
        elif isinstance(code_or_list, str):
            code = code_or_list
        else:
            code = None 

        if not code:
            self.add_to_chat("[錯誤] 未能從模型回覆中提取程式碼。", 'error')
            return # 終止任務
        
        self.session_data['current_code'] = code
        self.add_to_chat(f"\n=== 模型回覆 (程式碼) ===\n```python\n{code}\n```", 'ai')


        # 步驟 4: 產生解釋
        self.add_to_chat("\n[提示] 正在生成程式碼解釋...", 'system')
        
        # (!!!) 耗時操作
        explain_prompt = build_explain_prompt(self.session_data['user_need'], code)
        explain_resp = generate_response(explain_prompt)
        
        self.add_to_chat(f"\n=== 模型回覆 (解釋) ===\n{explain_resp}\n", 'ai')
        
        # 步驟 5: 詢問是否驗證
        self.add_to_chat("要執行程式 (包含 main 中的測試) 嗎? (y: 執行測試, n: 不驗證)", 'system')
        verify = (yield).strip().lower() # 暫停，等待 y/n

        if verify in ("y", "yes"):
            self.add_to_chat("\n[驗證中] 正在使用 AI 生成的測資逐一驗證...", 'system')
            
            # (!!!) 耗時操作 (內部有多次執行)
            # 呼叫重構的驗證邏輯
            self.run_validation_logic(
                code, 
                json_tests, 
                on_failure_callback=None # 模式 1 中驗證失敗不觸發自動分析
            )
        else:
             self.add_to_chat("[提示] 略過驗證。", 'system')

        # 步驟 6: 詢問是否進入修改模式
        self.add_to_chat("\n" + "="*20 + "\n程式碼已生成。", 'system')
        self.add_to_chat("是否要進入互動式修改模式？(y/n)", 'system')
        
        modify = (yield).strip().lower() # 暫停，等待 y/n
        
        if modify not in ("y", "yes"):
            self.add_to_chat("[提示] 略過修改，返回主選單。", 'system')
            return # 終止任務

        # 步驟 7: 進入互動式修改模式
        self.add_to_chat(
            "\n=== 進入互動式修改模式 ===\n"
            "請輸入您的下一步操作：\n"
            "  - [修改/優化/重構]：輸入您的需求說明\n"
            "  - [驗證]：輸入 'VERIFY' 或 'V'\n"
            "  - [解釋]：輸入 'EXPLAIN' 或 'E'\n"
            "  - [完成]：輸入 'QUIT'", 
            'system'
        )
        
        while True:
            mod_input = (yield).strip() # 暫停，等待修改指令
            
            if mod_input.upper() == "QUIT":
                self.add_to_chat(f"\n開發模式結束。最終程式碼如下：\n```python\n{self.session_data['current_code']}\n```")
                self.add_to_chat("[提示] 返回主選單。", 'system')
                break # 退出修改迴圈，任務結束

            elif mod_input.upper() in ("VERIFY", "V"):
                self.add_to_chat("\n[驗證中] 正在使用 AI 生成的測資逐一驗證 (當前程式碼)...", 'system')
                
                # (!!!) 耗時操作
                self.run_validation_logic(
                    self.session_data['current_code'], 
                    self.session_data['json_tests'],
                    on_failure_callback=None
                )
                self.add_to_chat("\n請輸入下一步操作 (修改, VERIFY, EXPLAIN, QUIT):", 'system')

            elif mod_input.upper() in ("EXPLAIN", "E"):
                self.add_to_chat("\n[解釋中] 產生當前程式碼的解釋...", 'system')
                
                # (!!!) 耗時操作
                explain_prompt = build_explain_prompt(
                    self.session_data['user_need'], 
                    self.session_data['current_code']
                )
                explain_resp = generate_response(explain_prompt)
                
                self.add_to_chat(f"\n=== 程式碼解釋 ===\n{explain_resp}", 'ai')
                self.add_to_chat("\n請輸入下一步操作 (修改, VERIFY, EXPLAIN, QUIT):", 'system')

            else: 
                modification_request = mod_input
                self.add_to_chat(f"\n[修正中] 正在根據您的要求 '{modification_request}' 修正程式碼...", 'system')

                # (!!!) 耗時操作
                fix_prompt_string = build_fix_code_prompt(
                    user_need=self.session_data['user_need'], 
                    virtual_code=self.session_data['virtual_code'], 
                    ai_generated_tests=self.session_data['json_tests'],
                    history=self.session_data['history'], 
                    current_code=self.session_data['current_code'], 
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
                    self.session_data['current_code'] = new_code
                    self.session_data['history'].append(f"修改: {modification_request}")
                    self.add_to_chat(f"\n=== 程式碼 (新版本) ===\n```python\n{new_code}\n```")
                else:
                    self.add_to_chat("[警告] 模型無法生成修正後的程式碼。請重試或輸入更明確的指令。", 'error')
                
                self.add_to_chat("\n請輸入下一步操作 (修改, VERIFY, EXPLAIN, QUIT):", 'system')
        
        # 任務結束 (隱式 Return)


    # --- (*** 新增 ***) 模式 2: 出題 ---
    def mode2_flow_quiz(self):
        """模式 2: 出題 (重構自 quiz_mode.py)"""
        
        self.add_to_chat("[系統] 進入模式 2: 出題。\n[載入中] 正在掃描題庫單元...", 'system')
        
        # (!!!) 耗時操作 (I/O)
        units = list_obj_units()
        
        if not units:
            self.add_to_chat("[錯誤] 找不到任何單元資料夾 (如 data/lessons 或 data/Leetcode)。", 'error')
            return

        unit_list_str = "\n".join(f"{idx}. {name}" for idx, name in enumerate(units, 1))
        self.add_to_chat(f"請選擇單元：\n{unit_list_str}\n\n請在下方輸入單元編號:", 'system')
        
        sel = (yield).strip() # 暫停，等待單元編號

        if not sel.isdigit() or not (1 <= int(sel) <= len(units)):
            self.add_to_chat("[錯誤] 請輸入有效的編號。", 'error')
            return

        unit = units[int(sel) - 1]
        self.add_to_chat(f"[載入中] 正在從 {unit} 載入題庫...", 'system')

        # (!!!) 耗時操作 (I/O)
        practices = load_all_coding_practice(unit=unit)
        
        if not practices:
            self.add_to_chat("[錯誤] 此單元沒有練習題。", 'error')
            return

        q = random.choice(practices)
        self.session_data['quiz_question'] = q # 儲存題目以便後續分析
        
        self.add_to_chat(
            f"\n=== 出題模式 ===\n"
            f"單元: {unit} (來源: {q.get('source_file', 'N/A')})\n"
            f"標題: {q['title']}\n"
            f"描述: {q['description']}\n", 
            'system'
        )

        # 取得範例
        examples_data = q.get("examples")
        example_to_run = None

        if isinstance(examples_data, list) and examples_data:
            example_to_run = examples_data[0] # 取 LeetCode 第一個範例
            self.add_to_chat(f"範例 (LeetCode 格式): {example_to_run}", 'system')
        elif isinstance(examples_data, dict):
            example_to_run = examples_data # 取 Lesson 範例
            self.add_to_chat(f"範例 (Lesson 格式): {example_to_run}", 'system')
        else:
            self.add_to_chat(" (此題無範例)", 'system')
        
        self.session_data['example_to_run'] = example_to_run

        # 使用者輸入程式碼
        self.add_to_chat(
            "\n請輸入你的 Python 解答 (若為 LeetCode 題，請包含 class Solution: ...)，\n"
            "完成後按 '送出'。", 
            'system'
        )
        
        user_code = yield # 暫停，等待程式碼
        self.session_data['user_code'] = user_code
        
        if not user_code:
            self.add_to_chat("[提示] 沒有輸入程式碼，取消驗證。", 'error')
            return

        # 檢查 solution 是否為 LeetCode 格式
        is_leetcode_format = "class Solution" in q.get("solution", "")
        
        # --- (B) LeetCode 格式驗證 ---
        if is_leetcode_format:
            yield from self.run_quiz_validation_leetcode(q, user_code, example_to_run)
        
        # --- (C) stdin/stdout 格式驗證 ---
        elif example_to_run:
            yield from self.run_quiz_validation_stdin(q, user_code, example_to_run)
        
        # --- (A) 無範例 ---
        else:
            self.add_to_chat("\n[提示] 此題無範例，跳過驗證。", 'system')
        
        # 顯示參考解答
        self.add_to_chat(f"\n=== 參考解答 ===\n```python\n{q.get('solution', '[無解答]')}\n```", 'system')
        # 任務結束

    def run_quiz_validation_leetcode(self, q, user_code, example_to_run):
        """模式 2 的輔助 generator：執行 LeetCode 驗證"""
        
        test_input_str = str(example_to_run.get("input", ""))
        test_output_str = str(example_to_run.get("output", ""))
        reference_solution = q.get("solution")

        self.add_to_chat("\n[範例測資比對 (LeetCode 模式)]", 'system')
        self.add_to_chat(f"Input (解析為參數): {repr(test_input_str)}", 'system')
        self.add_to_chat(f"Expected Output (比對回傳值): {repr(test_output_str)}", 'system')
        
        # 1. 解析函式資訊
        func_name, arg_names, input_definitions = parse_leetcode_info(reference_solution, test_input_str)
        
        if func_name is None:
            self.add_to_chat("\n  結果: [跳過] ❌", 'error')
            self.add_to_chat(
                "  [提示] 此 LeetCode 題目格式為類別實例化 (如 KthLargest, MyLinkedList)，\n"
                "         或無法解析函式簽名，目前驗證器尚不支援此類題目。", 
                'error'
            )
            return
        
        # 2. 構建測試腳本 (Harness)
        harness_code = f"""
# --- 輔助類別 (ListNode, TreeNode, etc.) ---
{get_data_structures_preamble()}

# --- 使用者提交的程式碼 ---
{user_code}
# --- 

import sys
import json

def run_test_harness():
    try:
        # --- 定義範例輸入 ---
        {input_definitions}
        
        # --- 實例化並呼叫 ---
        instance = Solution()
        result = instance.{func_name}({', '.join(arg_names)})
        
        # --- 自動轉換輸出 (例如 ListNode -> list) ---
        final_result = auto_convert_output(result)
        
        # --- 打印原始結果 (非 repr) ---
        print(final_result)
        
    except Exception as e:
        print(f"HarnessExecutionError: {{e}}", file=sys.stderr)

# 執行測試
run_test_harness()
"""
        # 3. 執行驗證 (使用 testrun.py 的比對邏輯)
        # (!!!) 耗時操作
        exec_success, raw_output_str = validate_main_function(
            code=harness_code,
            stdin_input=None, # Harness 不接收 stdin
            expected_output=None # 我們手動比對
        )
        
        success = False
        output_msg = raw_output_str

        if exec_success:
            norm_expected = _normalize_output(test_output_str)
            norm_actual = _normalize_output(raw_output_str)
            
            if norm_expected == norm_actual:
                success = True
                output_msg = raw_output_str
            else:
                success = False
                output_msg = (
                    f"Actual Output:\n{raw_output_str}\n\n"
                    f"[Output Mismatch (Normalized)]\n"
                    f"Expected: {repr(norm_expected)}\n"
                    f"Got:      {repr(norm_actual)}"
                )
        
        # 4. 報告結果
        self.add_to_chat(f"  詳細資訊/執行結果:\n{output_msg}", 'system')
        if success:
            self.add_to_chat("  結果: [成功] 使用者程式碼正確 ✅", 'system')
        else:
            self.add_to_chat("  結果: [錯誤] 程式執行失敗或輸出與期望不符 ❌", 'error')
            self.add_to_chat("\n[提示] 程式執行失敗，開始分析...\n", 'system')
            
            # (!!!) 耗時操作
            analysis_result = explain_code_error(harness_code)
            
            self.add_to_chat(f"\n=== 模型分析 ===\n{analysis_result}", 'ai')
        
        yield # 只是為了讓它成為 generator

    def run_quiz_validation_stdin(self, q, user_code, example_to_run):
        """模式 2 的輔助 generator：執行 stdin/stdout 驗證"""
        
        test_input_str = str(example_to_run.get("input", ""))
        test_output_str = str(example_to_run.get("output", ""))

        self.add_to_chat("\n[範例測資比對 (stdin/stdout 模式)]", 'system')
        self.add_to_chat(f"Input (傳入 stdin): {repr(test_input_str)}", 'system')
        self.add_to_chat(f"Expected Output (比對 stdout): {repr(test_output_str)}", 'system')

        # (!!!) 耗時操作
        exec_success, raw_output_str = validate_main_function(
            code=user_code,
            stdin_input=test_input_str, 
            expected_output=None # 手動比對
        )
        
        success = False
        output_msg = raw_output_str

        if exec_success:
            norm_expected = _normalize_output(test_output_str)
            norm_actual = _normalize_output(raw_output_str)
            
            if norm_expected == norm_actual:
                success = True
                output_msg = raw_output_str
            else:
                success = False
                output_msg = (
                    f"Actual Output:\n{raw_output_str}\n\n"
                    f"[Output Mismatch (Normalized)]\n"
                    f"Expected: {repr(norm_expected)}\n"
                    f"Got:      {repr(norm_actual)}"
                )
        
        self.add_to_chat(f"  詳細資訊/執行結果:\n{output_msg}", 'system')
        if success:
            self.add_to_chat("  結果: [成功] 使用者程式碼正確 ✅", 'system')
        else:
            self.add_to_chat("  結果: [錯誤] 程式執行失敗或輸出與期望不符 ❌", 'error')
            self.add_to_chat("\n[提示] 程式執行失敗，開始分析...\n", 'system')
            
            # (!!!) 耗時操作
            fallback_result = explain_code_error(user_code)
            
            self.add_to_chat(f"\n=== 模型分析 ===\n{fallback_result}", 'ai')
        
        yield # 只是為了讓它成為 generator
        
    # --- 模式 3: 驗證程式碼 (完整流程) ---
    def mode3_flow(self):
        """模式 3 的完整流程 (作為 Generator)"""
        
        # 步驟 1: 獲取程式碼
        self.add_to_chat("[系統] 進入模式 3: 使用者程式碼驗證。\n請貼上您要驗證的 Python 程式碼，然後按 '送出'。", 'system')
        user_code = yield  # 暫停，等待程式碼
        self.session_data = {'user_code': user_code}
        
        self.add_to_chat(f"收到的程式碼：\n```python\n{user_code}\n```", 'system')

        # 步驟 2: 獲取需求說明
        self.add_to_chat("\n請輸入這段程式碼的「需求說明」，AI 將以此生成測資來驗證。\n(若留空，則僅執行一次程式)", 'system')
        user_need = (yield).strip() # 暫停，等待需求
        
        json_tests = []
        if user_need:
            self.session_data['user_need'] = user_need
            self.add_to_chat("\n[提示] 正在根據您的需求說明生成測資...\n", 'system')
            
            # (!!!) 耗時操作
            test_prompt = build_test_prompt(user_need)
            test_resp = generate_response(test_prompt)
            
            self.add_to_chat(f"\n=== 模型回覆 (測資) ===\n{test_resp}\n", 'ai')
            
            json_tests = extract_json_block(test_resp) or parse_tests_from_text(test_resp) # 
            
            if json_tests:
                self.add_to_chat(f"[提示] 已成功提取 {len(json_tests)} 筆測資。", 'system')
            else:
                self.add_to_chat("[警告] 未能從模型回覆中提取 JSON 測資。將僅執行一次程式。", 'error')
        
        # 步驟 3: 執行驗證
        if json_tests:
            self.add_to_chat("\n[驗證中] 正在使用 AI 生成的測資逐一驗證您的程式碼...", 'system')
            
            # (!!!) 耗時操作
            # 呼叫驗證邏輯，並傳入失敗時的回呼函式
            all_passed = self.run_validation_logic(
                user_code, 
                json_tests, 
                on_failure_callback=self.mode3_analyze_error
            )
            
            if all_passed:
                self.add_to_chat("\n" + "="*20 + "\n總結: [成功] 您的程式碼已通過所有 AI 生成的測資。", 'system')
        else:
            # (B) 如果沒有測資，執行旧的 Mode 3 邏輯 (僅執行一次)
            self.add_to_chat("\n=== 驗證中 (僅執行一次，無輸入) ===\n", 'system')
            
            # (!!!) 耗時操作
            success, result_msg = validate_main_function(user_code, stdin_input=None, expected_output=None)

            if success:
                self.add_to_chat("\n=== 程式執行成功 ===\nSTDOUT 輸出:\n" + (result_msg or "[無輸出]"), 'system')
            else:
                self.add_to_chat("\n=== 程式執行失敗 ===\nSTDERR 或錯誤訊息:\n" + result_msg, 'error')
                self.add_to_chat("\n[警告] 程式執行失敗，開始分析...\n", 'system')
                
                # (!!!) 耗時操作
                self.mode3_analyze_error() # 呼叫分析
        
        # 任務結束 (隱式 Return)

    def mode3_analyze_error(self):
        """模式 3 驗證失敗時的分析回呼函式 (在執行緒中執行)"""
        try:
            user_code = self.session_data.get('user_code')
            if not user_code:
                return # 
            
            # (!!!) 耗時操作
            fallback_result = explain_code_error(user_code) 
            
            self.add_to_chat(f"\n=== 程式碼錯誤分析 ===\n{fallback_result}", 'ai')
        except Exception as e:
            self.add_to_chat(f"\n[分析失敗] {e}", 'error')

    # --- (*** 新增 ***) 模式 4: 程式碼解釋 ---
    def mode4_flow_explain(self):
        """模式 4: 程式碼解釋 (重構自 explain_user_code.py)"""
        
        self.add_to_chat("[系統] 進入模式 4: 程式碼解釋。\n請貼上您要解釋的 Python 程式碼，然後按 '送出'。", 'system')
        user_code = yield # 暫停，等待程式碼
        
        if not user_code.strip():
            self.add_to_chat("[提示] 沒有輸入程式碼。", 'error')
            return

        self.add_to_chat("\n請輸入需求 (用於解釋背景，可留空):", 'system')
        user_need = (yield).strip() # 暫停，等待需求
        
        self.add_to_chat("\n[系統] 正在生成程式碼解釋...", 'system')

        # (!!!) 耗時操作
        explain_prompt = build_explain_prompt(user_need, user_code)
        explain_resp = generate_response(explain_prompt)

        self.add_to_chat(f"\n=== 模型回覆 (解釋) ===\n{explain_resp}\n", 'ai')
        # 任務結束

    # --- (*** 新增 ***) 模式 5: 翻譯 ---
    def mode5_flow_translate(self):
        """模式 5: 翻譯 (重構自 model_interface.py)"""
        
        self.add_to_chat("[系統] 進入模式 5: 翻譯。\n請輸入目標語言 (例如: 英文, 繁體中文, 日文) [預設: 英文]:", 'system')
        target_lang = (yield).strip() # 暫停，等待語言
        
        if not target_lang:
            target_lang = "英文"
            
        self.add_to_chat(f"\n請輸入要翻譯成「{target_lang}」的文字，然後按 '送出'。", 'system')
        text_to_translate = (yield).strip() # 暫停，等待文字

        if not text_to_translate:
            self.add_to_chat("[提示] 沒有輸入內容。", 'error')
            return

        self.add_to_chat(f"\n[系統] 正在翻譯為「{target_lang}」...", 'system')
        
        # (!!!) 耗時操作
        prompt = build_translate_prompt(text_to_translate, target_lang)
        translated_text = generate_response(prompt)
        
        self.add_to_chat(f"\n=== 翻譯結果 ===\n{translated_text}", 'ai')
        # 任務結束

    # --- (*** 新增 ***) 模式 6: 程式碼建議 ---
    def mode6_flow_suggestions(self):
        """模式 6: 獲取程式碼建議 (重構自 model_interface.py)"""
        
        self.add_to_chat("[系統] 進入模式 6: 程式碼建議。\nAI 將根據您的需求和程式碼，提供 2-4 個改進提示。", 'system')
        
        self.add_to_chat("\n請輸入這段程式碼的「需求說明」，AI 將以此為基準提供建議。", 'system')
        user_need = (yield).strip() # 暫停，等待需求

        if not user_need:
            self.add_to_chat("[提示] 未提供需求說明，AI 將僅根據程式碼本身提供通用建議。", 'system')

        self.add_to_chat("\n請貼上您要獲取建議的 Python 程式碼，然後按 '送出'。", 'system')
        user_code = yield # 暫停，等待程式碼

        if not user_code.strip():
            self.add_to_chat("[提示] 沒有輸入程式碼，取消操作。", 'error')
            return

        self.add_to_chat("\n[系統] 正在分析您的程式碼並生成建議...", 'system')
        
        # (!!!) 耗時操作
        prompt = build_suggestion_prompt(user_need, user_code)
        suggestions = generate_response(prompt)
        
        self.add_to_chat(f"\n=== AI 程式碼建議 ===\n{suggestions}", 'ai')
        # 任務結束

    # --- (*** 新增 ***) 聊天模式 ---
    def chat_flow(self):
        """聊天模式 (重構自 model_interface.py)"""
        
        self.add_to_chat("[系統] 進入聊天模式。\n請輸入您的問題。 (輸入 'QUIT' 結束此模式)", 'system')
        
        while True:
            user_input = (yield).strip() # 暫停，等待輸入
            
            if user_input.upper() == "QUIT":
                self.add_to_chat("[系統] 結束聊天模式。", 'system')
                break # 退出迴圈，任務結束

            self.add_to_chat("[系統] 思考中...", 'system')
            
            prompt = ""
            # 偵測是否貼了 Python 程式碼
            if "def " in user_input or "print(" in user_input or "for " in user_input or "import " in user_input:
                self.add_to_chat("[提示] 偵測到 Python 程式碼，進入解釋模式...", 'system')
                prompt = build_explain_prompt("使用者貼上的程式碼", user_input)
            else:
                # 為基礎聊天模式加入助教身份
                prompt = (
                    "用繁體中文回答。\n"
                    "你是一位友善且專業的程式學習助教。\n"
                    "請用白話、簡單易懂的方式回答使用者的程式相關問題。\n\n"
                    f"使用者問題：\n{user_input}"
                )

            # (!!!) 耗時操作
            resp = generate_response(prompt)
            
            self.add_to_chat(f"{resp}", 'ai')
            self.add_to_chat("\n請繼續提問 (輸入 'QUIT' 結束此模式)", 'system')
            
        # 任務結束 (隱式 Return)

    # --- 驗證邏輯 (重構為輔助函式) ---
    def run_validation_logic(self, code, json_tests, on_failure_callback=None):
        """
        執行 main.py 中的驗證迴圈。
        (這整個函式在背景執行緒中執行)
        返回 True (全部通過) 或 False (有失敗)
        """
        if not json_tests:
            self.add_to_chat("[警告] 找不到 AI 生成的 JSON 測資。僅執行一次 (無輸入)...", 'error')
            
            # (!!!) 耗時操作
            success, output_msg = validate_main_function(code, stdin_input=None, expected_output=None)
            
            self.add_to_chat(f"執行結果 (無輸入): {'成功' if success else '失敗'}\n{output_msg}", 'system' if success else 'error')
            if not success and on_failure_callback:
                on_failure_callback()
            return success

        all_passed = True
        failed_outputs = [] # 儲存失敗訊息
        
        for i, test in enumerate(json_tests):
            self.add_to_chat(f"\n--- 測試案例 {i+1} ---", 'system')
            
            if not (isinstance(test, list) and len(test) == 2):
                self.add_to_chat(f"  [警告] 測資格式不符 (應為 [input, output]): {repr(test)}\n  結果: [跳過]", 'error')
                all_passed = False 
                continue 
            
            test_input_val, test_output_val = test[0], test[1]
            
            self.add_to_chat(f"  Input: {repr(test_input_val)}\n  Expected Output: {repr(test_output_val)}", 'system')

            test_input_str = str(test_input_val) if test_input_val is not None else None
            test_output_str = str(test_output_val) if test_output_val is not None else None

            # (!!!) 耗時操作
            success, output_msg = validate_main_function(
                code=code,
                stdin_input=test_input_str,
                expected_output=test_output_str
            )
            
            self.add_to_chat(f"  詳細資訊/執行結果:\n{output_msg}", 'system')
            
            if success:
                self.add_to_chat(f"  結果: [通過] ✅", 'system')
            else:
                self.add_to_chat(f"  結果: [失敗] ❌", 'error')
                all_passed = False
                failed_outputs.append(f"案例 {i+1} (Input: {repr(test_input_str)}):\n{output_msg}")

        self.add_to_chat("\n" + "="*20, 'system')
        if all_passed:
            self.add_to_chat("總結: [成功] 所有測資均已通過。", 'system')
        else:
            self.add_to_chat("總結: [失敗] 部分測資未通過。", 'error')
            if on_failure_callback:
                self.add_to_chat("\n[警告] 程式驗證失敗，開始分析...\n", 'system')
                # 顯示第一個錯誤
                self.add_to_chat(f"(失敗詳情: {failed_outputs[0]})", 'error')
                on_failure_callback()
        
        return all_passed

    # --- 其他模式的存根 (Stub) ---
    def stub_flow(self, mode_name, function_name):
        """
        一個通用的存根 generator，用於提示使用者哪些功能需要重構。
        (*** 此函式現在不再被 set_mode 使用 ***)
        """
        self.add_to_chat(
            f"[系統] 進入 {mode_name}。\n"
            f"[警告] 此功能 (呼叫 `{function_name}()`) 尚未與 GUI 整合。\n"
            f"`{function_name}` 是一個使用 `input()` 和 `print()` 的同步函式，"
            f"它會凍結 GUI。必須將其重構為非阻塞函式 (例如，像 `mode1_flow` 一樣的 Generator) 才能在 GUI 中使用。",
            'error'
        )
        # 任務立即結束
        return


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = ChatApplication(root)
        root.mainloop()
    except KeyboardInterrupt:
        print("\n使用者中斷，結束。")