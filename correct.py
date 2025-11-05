import json
import glob
import collections 
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os
from matplotlib.ticker import FuncFormatter # 導入格式化工具

# --- 嘗試設定中文字體 ---
# Colab/Linux 環境中常見的中文字體
font_path = '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf' 
# 備用路徑 (如果有的話)
if not os.path.exists(font_path):
    # 嘗試 Windows 常見字體 (不一定存在於 Colab/Linux)
    font_path_win = '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc' # 文泉驛禪黑
    if os.path.exists(font_path_win):
        font_path = font_path_win
    else:
        # 如果都找不到，使用預設字體 (中文可能顯示為方塊)
        print("警告：未找到指定的中文字體，圖表中的中文可能無法顯示。")
        font_path = None

my_font = fm.FontProperties(fname=font_path)
plt.rcParams['axes.unicode_minus'] = False # 解決負號顯示問題
# --- 字體設定結束 ---

# 總數，用於計算成功率 (使用浮點數確保除法精確)
TOTAL_COUNT = 439.0

# 更改目標：讀取 results 檔案以獲取 failure_count
results_files = [
f"result_pro/summary_run_{i}.json" for i in range(1, 51)
]

chart_data = []
print(f"開始處理 {len(results_files)} 個 result 檔案，以提取 'failure_count' 並計算成功率 (總數: {int(TOTAL_COUNT)})...")

for file_path in results_files:
    print(f"--- 正在處理 {file_path} ---")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 提取 failure_count
            # 使用 .get() 來安全地獲取鍵值，如果鍵不存在則返回 None
            failure_count = data.get("generation_or_validation_failure_count", None)
            
            if failure_count is not None:
                # 計算成功率
                success_rate = (TOTAL_COUNT - failure_count) / TOTAL_COUNT
                
                # 為了圖表標籤更簡潔，只取檔案名（例如 "results_run_1"）
                clean_name = file_path.split('/')[-1].replace('.json', '') 
                
                chart_data.append({
                    "run_name": clean_name,
                    "failure_count": failure_count,
                    "success_rate": success_rate
                })
                print(f"  找到 failure_count: {failure_count}，成功率: {success_rate:.2%}")
            else:
                print(f"  在 {file_path} 中未找到 'failure_count' 鍵。")
                
    except FileNotFoundError:
        # 這是預期行為，因為您只上傳了 1-3 號檔案
        print(f"  錯誤：找不到檔案 {file_path}")
    except json.JSONDecodeError:
        print(f"  錯誤：無法解析 {file_path} 的 JSON 內容")
    except Exception as e:
        print(f"  處理 {file_path} 時發生錯誤：{e}")

# --- 檢查是否有資料並使用 Matplotlib 繪圖 ---
if not chart_data:
    print("\n沒有找到任何 'failure_count' 資料，無法產生圖表。")
else:
    print(f"\n成功提取 {len(chart_data)} 筆資料，正在產生圖表...")
    
    # 提取標籤和值
    labels = [item['run_name'] for item in chart_data]
    failure_values = [item['failure_count'] for item in chart_data]
    success_values = [item['success_rate'] for item in chart_data]
    
    # --- 圖表 1：失敗次數 (Failure Count) ---
    try:
        plt.figure(figsize=(14, 6)) # 設定圖表大小
        
        # --- 新增：設定最高/最低顏色 ---
        max_fail = max(failure_values)
        min_fail = min(failure_values)
        
        color_default_fail = (0/255, 0/255, 0/255, 0.6) # 預設紅色
        color_max_fail = (220/255, 20/255, 60/255, 0.9)     # 最差 (深紅)
        color_min_fail = (74/255, 161/255, 74/255, 0.7)   # 最好 (綠色)
        
        bar_colors_fail = []
        for val in failure_values:
            if val == max_fail:
                bar_colors_fail.append(color_max_fail)
            elif val == min_fail:
                bar_colors_fail.append(color_min_fail)
            else:
                bar_colors_fail.append(color_default_fail)
        # --- 顏色設定結束 ---

        # 修正：使用 bar_colors_fail 列表
        bars = plt.bar(labels, failure_values, color=bar_colors_fail) 
        
        # 設定標題和標籤 (使用中文字體)
        plt.title('', fontproperties=my_font)
        plt.xlabel('Run', fontproperties=my_font)
        plt.ylabel('Failure Count', fontproperties=my_font)
        
        # 旋轉 X 軸標籤，防止重疊
        plt.xticks(rotation=45, ha='right')
        
        # 確保 Y 軸為整數
        max_val = max(failure_values)
        step = 5 if max_val < 50 else 10
        plt.yticks(range(0, max_val + step, step))

        
        # 在長條圖頂端顯示數字
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, yval, int(yval), va='bottom', ha='center', fontsize=8) 

        plt.tight_layout() # 自動調整佈局
        
        # 儲存圖表
        output_image_filename = 'failure_chart_pro.png'
        plt.savefig(output_image_filename)
        
        print(f"\n成功將「失敗次數」圖表儲存為 {output_image_filename}")

    except Exception as e:
        print(f"\n使用 Matplotlib 繪製「失敗次數」圖表時發生錯誤：{e}")

    # --- 圖表 2：成功率 (Success Rate) ---
    try:
        print("\n正在產生「成功率」圖表...")
        plt.figure(figsize=(14, 6)) # 建立新圖表
        
        # --- 新增：計算平均、最高、最低並設定顏色 ---
        average_success_rate = sum(success_values) / len(success_values)
        max_rate = max(success_values)
        min_rate = min(success_values)

        color_default_succ = (0/255, 0/255, 0/255, 0.7) # 預設綠色
        color_max_succ = (34/255, 139/255, 34/255, 0.9)     # 最好 (深綠)
        color_min_succ = (239/255, 68/255, 68/255, 0.6)   # 最差 (紅色)
        
        bar_colors_success = []
        for rate in success_values:
            if rate == max_rate:
                bar_colors_success.append(color_max_succ)
            elif rate == min_rate:
                bar_colors_success.append(color_min_succ)
            else:
                bar_colors_success.append(color_default_succ)
        # --- 顏色設定結束 ---

        # 修正：使用 bar_colors_success 列表
        bars = plt.bar(labels, success_values, color=bar_colors_success) 
        
        # 設定標題和標籤
        plt.title('', fontproperties=my_font)
        plt.xlabel('Run', fontproperties=my_font)
        plt.ylabel('Success Rate', fontproperties=my_font)
        
        # 旋轉 X 軸標籤
        plt.xticks(rotation=45, ha='right')
        
        # 設定 Y 軸範圍 0% 到 105%
        # plt.ylim(0, 1.05)
        
        # 格式化 Y 軸為百分比
        ax = plt.gca()
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f'{y:.0%}'))

        # 獲取當前的 Y 軸刻度
        current_ticks = list(ax.get_yticks())
        
        # 添加平均成功率到刻度列表中 (如果尚未存在)
        if average_success_rate not in current_ticks:
            current_ticks.append(average_success_rate)
            
        # 排序刻度，確保 Y 軸順序正確
        current_ticks.sort() 
        
        # 設置包含平均值的新 Y 軸刻度
        ax.set_yticks(current_ticks)
        
        # --- 新增：繪製平均線和圖例 ---
        plt.axhline(y=average_success_rate, color='blue', linestyle='--', linewidth=1.5, 
                    label=f'average: {average_success_rate:.1%}')
        # plt.legend(prop=my_font) # 顯示圖例 (包含平均線標籤)
        # --- 平均線結束 ---
        
        # 在長條圖頂端顯示百分比
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2.0, yval, f'{yval:.1%}', va='bottom', ha='center', fontsize=8) 
        plt.ylim(0, 1.00)
        plt.tight_layout() # 自動調整佈局
        
        # 儲存圖表
        success_chart_filename = 'success_rate_chart_pro.png'
        plt.savefig(success_chart_filename)
        
        print(f"\n成功將「成功率」圖表儲存為 {success_chart_filename}")

    except Exception as e:
        print(f"\n使用 Matplotlib 繪製「成功率」圖表時發生錯誤：{e}")