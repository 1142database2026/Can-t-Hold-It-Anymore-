import pandas as pd
from datetime import datetime

# =========================
# 設定檔案路徑
# =========================
SEVEN_ELEVEN_FILE = "seven_eleven.csv"
FAMILYMART_FILE = "familymart.csv"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M")
OUTPUT_FILE = "store_merged.csv"

# =========================
# 讀取並加上 brand_id
# =========================
def load_with_brand(file_path, brand_id, brand_name):
    print(f"正在讀取 {brand_name}：{file_path}")
    df = pd.read_csv(file_path, encoding="utf-8-sig")
    df.insert(0, "brand_id", brand_id)
    print(f"  → 共 {len(df)} 筆")
    return df

# =========================
# 主程式
# =========================
def main():
    df_711 = load_with_brand(SEVEN_ELEVEN_FILE, 1, "統一超商 (7-ELEVEN)")
    df_fm  = load_with_brand(FAMILYMART_FILE,   2, "全家超商 (FamilyMart)")

    # 欄位一致性檢查
    if list(df_711.columns) != list(df_fm.columns):
        print("\n⚠️  兩份資料欄位不完全相同，將以 brand_id 對齊後合併：")
        print(f"  7-ELEVEN 欄位：{list(df_711.columns)}")
        print(f"  FamilyMart 欄位：{list(df_fm.columns)}")

    # 合併：統一超商在前，全家在後
    df_merged = pd.concat([df_711, df_fm], ignore_index=True)

    # 輸出
    df_merged.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n✅ 合併完成！已輸出：{OUTPUT_FILE}")
    print(f"   總筆數：{len(df_merged)}（7-ELEVEN: {len(df_711)}，FamilyMart: {len(df_fm)}）")

if __name__ == "__main__":
    main()