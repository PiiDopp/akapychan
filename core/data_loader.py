import os
import json
from typing import List, Dict, Any, Tuple, Optional
import pathlib

def load_all_json_from_dir(root_dir: str = "obj/LEETCODE") -> List[Dict[str, Any]]:
    """
    遞迴地從指定目錄載入所有 JSON 檔案的內容。

    Args:
        root_dir: 包含 JSON 資料集的根目錄。

    Returns:
        一個包含所有 JSON 內容字典的列表。
    """
    all_data = []
    # 確保路徑存在
    if not os.path.exists(root_dir):
        # 這裡不報錯，僅輸出警告，讓程式碼可以繼續執行。
        print(f"警告：資料目錄 '{root_dir}' 不存在，無法載入 RAG 資料。")
        return []

    # 遞迴遍歷資料夾
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".json"):
                file_path = os.path.join(dirpath, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                        # 為了 RAG 方便識別，在內容中加入來源檔案名
                        if isinstance(content, dict):
                            content['source_file'] = file_path
                        all_data.append(content)
                except Exception as e:
                    print(f"錯誤：無法載入 JSON 檔案 {file_path}: {e}")
    return all_data

def format_data_for_rag(data: List[Dict[str, Any]]) -> str:
    """
    將載入的 JSON 資料格式化為模型可以理解的 RAG 上下文。
    為了避免 Prompt 過長，這裡只取部分關鍵資訊。
    """
    formatted_chunks = []
    
    # 限制只取前 10 個檔案的資料，避免 Prompt 超長
    for item in data[:10]:
        source = item.get('source_file', 'Unknown')
        title = item.get('title', 'No Title')
        
        # 嘗試從 'test_cases' 中取出測資，或其他關鍵數據
        test_cases = item.get('test_cases', 'No test cases provided.')
        
        # 建立一個簡潔的上下文片段
        chunk = (
            f"--- Context Source: {source} (Title: {title}) ---\n"
            f"關鍵數據: {json.dumps(test_cases, ensure_ascii=False, indent=2) if test_cases != 'No test cases provided.' else json.dumps(item, ensure_ascii=False, indent=2)[:500] + '...'}\n"
        )
        formatted_chunks.append(chunk)

    return "\n\n".join(formatted_chunks)


def load_all_problems_from_file(file_path: pathlib.Path) -> List[Tuple[str, str, List[Dict[str, str]], Optional[str]]]:
    """
    (從 testrun.py 移入)
    從指定的 JSON 檔案彈性載入 *所有* 練習題的需求描述、範例和參考解法。
    
    返回一個元組的 *列表*：
    List[ (title, description, examples, solution), ... ]
    
    如果檔案無法解析或未找到任何題目，則返回一個空列表。
    """
    all_problems = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        default_title = file_path.stem
        problems_list = []

        # 1. 嘗試 'coding_practice' 結構 (這現在是一個列表)
        if "coding_practice" in data and isinstance(data["coding_practice"], list):
            problems_list = data["coding_practice"]
        
        # 2. 備用：如果頂層就是一個有效的題目結構（雖然不常見）
        elif "description" in data or "solution" in data:
             # 將整個頂層 data 視為單一問題
             problems_list = [data]

        if not problems_list:
            print(f"  [警告] 在 {file_path.name} 中找不到 'coding_practice' 列表或有效的頂層題目。")
            return []

        # --- 迭代檔案中的 *所有* 題目 ---
        for index, problem in enumerate(problems_list):
            if not isinstance(problem, dict):
                print(f"  [警告] {file_path.name} 中索引 {index} 處的項目不是一個有效的物件（字典）。")
                continue

            title = problem.get("title", f"{default_title}_problem_{index+1}")
            description = problem.get("description", problem.get("content"))
            solution = problem.get("solution")
            raw_examples = problem.get("examples")
            examples = []

            # 格式化 examples
            if isinstance(raw_examples, list):
                examples = raw_examples
            elif isinstance(raw_examples, dict):
                 examples = [raw_examples]

            formatted_examples = []
            if examples:
                 for ex in examples:
                     inp = ex.get("input")
                     out = ex.get("output")
                     if inp is not None and out is not None:
                         formatted_examples.append({
                             "input": str(inp),
                             "output": str(out)
                         })

            # 確保 solution 是字串或 None
            if solution and not isinstance(solution, str):
                solution = None # 如果格式不對，設為 None

            # 必須要有 description
            if description and isinstance(description, str) and description.strip():
                all_problems.append(
                    (title, description.strip(), formatted_examples, solution)
                )
            else:
                 print(f"  [警告] {file_path.name} 中索引 {index} 處的題目缺少 'description'。")

        return all_problems

    except Exception as e:
        print(f"  [錯誤] 讀取或解析 {file_path.name} 時發生例外: {e}")
        return [] # 返回空列表表示失敗

if __name__ == '__main__':
    # 修正後的測試載入功能：直接使用預設路徑 'project/obj'，因為腳本從 project/ 目錄執行
    print("--- 執行 data_loader.py 測試載入 (應找到 project/obj) ---")
    data = load_all_json_from_dir() 
    print(f"成功載入 {len(data)} 個檔案。")
    if data:
        rag_context = format_data_for_rag(data)
        print("\n--- RAG 格式化上下文範例 (前 500 字) ---\n")
        print(rag_context[:500] + "...")