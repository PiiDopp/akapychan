import json
import collections
import glob
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# --- Font Setup for Matplotlib (to support CJK characters) ---
# 嘗試設定一個支援 CJK 字元的字體堆疊
try:
    # 'sans-serif' 是一個備用選項
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False # 正確處理負號
    print("Matplotlib font set to support CJK (if fonts are available).")
except Exception as e:
    print(f"Warning: Could not set CJK font for matplotlib. Plot labels might not render correctly. Error: {e}")
# --- End Font Setup ---


def find_title_values(obj, counter):
    """
    遞迴搜尋資料結構中所有名為 'title' 的鍵，
    並在其對應的值的計數器中加 1。
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'title':
                # 嘗試直接使用該值作為 counter 的鍵
                # 如果值是不可雜湊的 (如 list 或 dict)，
                # 則將其轉換為字串後再作為鍵
                try:
                    # 處理 None 值，將其轉換為字串 'None'
                    key = v if v is not None else 'None'
                    counter[key] += 1
                except TypeError: 
                    # 捕獲不可雜湊型別（如 list, dict）的錯誤
                    counter[str(v)] += 1
            
            # 繼續遞迴搜尋 'value'
            find_title_values(v, counter)
    elif isinstance(obj, list):
        # 如果是 list，則遞迴搜尋每個元素
        for item in obj:
            find_title_values(item, counter)

def plot_frequent_titles(sorted_titles, threshold=15, output_image_file='title_counts_chart.png'):
    """
    將出現次數超過 threshold 的 'title' 畫成水平長條圖。
    
    Args:
        sorted_titles (list): (value, count) tuples 列表, 應按 count 降序排列。
        threshold (int): 畫入圖表的最小次數門檻。
        output_image_file (str): 儲存圖表的檔案名稱。
    """
    print(f"\n--- 正在生成出現次數 > {threshold} 次的 'title' 圖表 ---")
    
    # 1. 篩選出超過 threshold 的資料
    # sorted_titles 已經是 (value, count) 的 tuple 列表，按 count 降序排列
    frequent_titles = [(title, count) for title, count in sorted_titles if count > threshold]
    
    if not frequent_titles:
        print(f"沒有 'title' 的出現次數超過 {threshold} 次，不生成圖表。")
        return

    print(f"找到 {len(frequent_titles)} 個 'title' 出現次數超過 {threshold} 次。")

    # 2. 準備繪圖資料
    #
    # 我們希望長條圖中，次數最高的在最上面。
    # frequent_titles 已經是降序了 (e.g., [('A', 50), ('B', 30), ('C', 20)])
    # 傳給 plt.barh 時，它會從下往上畫，所以我們需要反轉 (reverse) 列表。
    frequent_titles.reverse() # In-place reverse
    
    labels = [item[0] for item in frequent_titles]
    counts = [item[1] for item in frequent_titles]
    
    # 3. 創建圖表
    # 根據標籤數量動態調整圖表高度
    # 基礎高度 4 英吋，每增加一個標籤增加 0.4 英吋
    fig_height = max(4, len(labels) * 0.4)
    plt.figure(figsize=(10, fig_height)) # 寬度 10 英吋
    
    bars = plt.barh(labels, counts, color='skyblue')
    
    # 在長條圖上顯示數字
    for bar in bars:
        plt.text(
            bar.get_width() + 0.1,  # X-position (just right of the bar)
            bar.get_y() + bar.get_height() / 2, # Y-position (center of the bar)
            f'{bar.get_width()}', # The text (count)
            va='center', # Vertical alignment
            ha='left' # Horizontal alignment
        )

    plt.xlabel('出現次數 (Count)')
    plt.ylabel('Title 內容')
    plt.title(f'出現次數超過 {threshold} 次的 Title')
    
    # 調整 x 軸範圍，確保標籤有空間
    plt.xlim(0, max(counts) * 1.15) 
    
    plt.tight_layout() # 自動調整邊距，確保標籤不被裁切
    
    # 4. 儲存圖表
    try:
        # 使用 bbox_inches='tight' 和 dpi 參數確保圖表品質和內容完整
        plt.savefig(output_image_file, bbox_inches='tight', dpi=150)
        print(f"成功將圖表儲存為 {output_image_file}")
    except Exception as e:
        print(f"儲存圖表時發生錯誤：{e}")


# --- 主程式 ---

# 指定要處理的 summary 檔案列表
summary_files = [
f"result_pro/summary_run_{i}.json" for i in range(1, 51)
]

# 建立一個 Counter 物件來儲存所有 'title' 內容的出現次數
total_title_counts = collections.Counter()

print(f"開始處理 {len(summary_files)} 個 summary 檔案中 'title' 鍵的對應內容...")

for file_path in summary_files:
    print(f"--- 正在處理 {file_path} ---")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 建立一個臨時 counter 來統計目前檔案的內容
            file_counter = collections.Counter()
            find_title_values(data, file_counter)
            
            if not file_counter:
                print(f"  在 {file_path} 中未找到任何 'title' 鍵。")
            else:
                print(f"  在此檔案中找到 {len(file_counter)} 種不同的 'title' 內容。")
                # 更新總計數器
                total_title_counts.update(file_counter)
                
    except json.JSONDecodeError:
        print(f"  錯誤：無法解析 {file_path} 的 JSON 內容")
    except FileNotFoundError:
        print(f"  錯誤：找不到檔案 {file_path}")
    except Exception as e:
        print(f"  處理 {file_path} 時發生錯誤：{e}")

# --- 輸出最終統計結果 ---
print("\n--- 總結：'title' 鍵對應內容的總出現次數 (跨所有檔案) ---")

output_filename = 'title_counts_pro.json'
# output_image_filename = 'title_counts_chart.png' # 定義圖片檔案名稱

if not total_title_counts:
    print("在所有 summary 檔案中，未找到任何 'title' 鍵。")
    output_data = {} # 確保 output_data 被定義
else:
    print(f"共找到 {len(total_title_counts)} 種不同的 'title' 內容：")
    
    # 1. 獲取排序後的列表 (從高到低)
    sorted_titles = total_title_counts.most_common()
    
    # 2. 將排序後的列表轉換為 OrderedDict 來保持順序 (用於 JSON)
    output_data = collections.OrderedDict(sorted_titles)

    # 3. 按照排序後的列表打印
    for value, count in sorted_titles: # 使用 sorted_titles
        print(f"  '{value}': {count} 次")
        
    # 4. 【新增功能】呼叫繪圖函式
    # 將排序好的 sorted_titles 傳入
    # plot_frequent_titles(sorted_titles, threshold=15, output_image_file=output_image_filename)

# --- 儲存 JSON 統計結果 ---
try:
    with open(output_filename, 'w', encoding='utf-8') as f:
        # 使用 ensure_ascii=False 來正確儲存中文等非 ASCII 字元
        # indent=4 讓 JSON 檔案格式更易讀
        json.dump(output_data, f, ensure_ascii=False, indent=4)
    print(f"\n成功將統計結果導出到 {output_filename}")
except Exception as e:
    print(f"\n導出到 JSON 時發生錯誤：{e}")