import requests
import pandas as pd
import re
import json
import ast
import time
from datetime import datetime

# =========================
# 基本設定
# =========================
FILE_PATH = "taiwan_area.xlsx"
BASE_URL = "https://api.map.com.tw/net/familyShop.aspx"
KEY = "6F30E8BF706D653965BDE302661D1241F8BE9EBC"

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://www.family.com.tw/",
    "User-Agent": "Mozilla/5.0"
}

TYPE_MAP = {
    "rest": "休憩區",
    "toilet": "廁所",
    "cs": "ChargeSPOT",
}

# =========================
# 全台地名自動正規化
# 臺 -> 台
# =========================
def normalize_tw_name(text):
    return str(text).strip().replace("臺", "台")


# =========================
# 全形英數 -> 半形英數
# 例：Ｂ１２３號 -> B123號
# =========================
def fullwidth_to_halfwidth(text):
    text = str(text)

    table = str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    )

    return text.translate(table)


# =========================
# 讀取行政區 Excel
# =========================
def load_areas_with_townid(file_path):
    print("正在讀取行政區資料：", file_path)

    df = pd.read_excel(file_path, engine="openpyxl")

    area_list = []
    townid_map = {}

    for _, row in df.iterrows():
        city = normalize_tw_name(row["city"]).strip()
        town = normalize_tw_name(row["town"]).strip()
        town_id = str(row["town_id"]).strip()

        area_list.append((city, town))
        townid_map[(city, town)] = town_id

    return area_list, townid_map


# =========================
# JSONP 解析
# =========================
def parse_jsonp(text):
    text = text.strip()

    m = re.search(r"\(\s*(\[.*\])\s*\)\s*;?\s*$", text, re.S)
    if not m:
        m = re.search(r"(\[.*\])", text, re.S)

    if not m:
        return []

    payload = m.group(1)

    for parser in (json.loads, ast.literal_eval):
        try:
            data = parser(payload)
            if isinstance(data, list):
                return data
        except:
            pass

    return []


# =========================
# API 呼叫
# =========================
def api_get(params, city, town, type_name):
    """
    params: API 請求參數
    city, town, type_name: 用於顯示錯誤訊息的資訊
    """
    for i in range(3):  # 最多嘗試 3 次
        try:
            r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
            r.encoding = "utf-8"
            data = parse_jsonp(r.text)
            
            if data:  # 如果抓到資料，直接回傳
                return data
            else:
                # 如果是空資料，紀錄並重試
                print(f"  ⚠️  [空值警告] {city}{town}({type_name}) 第 {i+1} 次嘗試無資料，重試中...")
                time.sleep(0.5) # 重試稍微停久一點，避開伺服器限流
        except Exception as e:
            print(f"  ❌  [連線錯誤] {city}{town}({type_name}) 第 {i+1} 次嘗試失敗: {e}")
            time.sleep(1)

    # 如果三次都跑完還是沒資料
    print(f"  🚨  [最終失敗] {city}{town} 的 {type_name} 服務回傳空值 (已嘗試 3 次)")
    return []


# =========================
# 抓門市資料
# =========================
def get_stores(city, town, type_code):
    # 從 TYPE_MAP 取得中文名稱，方便閱讀
    type_name = TYPE_MAP.get(type_code, type_code)
    
    params = {
        "searchType": "ShopList",
        "type": type_code,
        "city": city,
        "area": town,
        "road": "",
        "fun": "showStoreList",
        "key": KEY
    }
    # 將 city, town, type_name 傳進去
    return api_get(params, city, town, type_name)


# =========================
# 地址清理
# 去除 city + town
# 並將全形數字轉半形
# =========================
def clean_address(address, city, town):
    address = str(address).strip()

    if address.startswith(city + town):
        address = address[len(city + town):]

    elif address.startswith(city):
        address = address[len(city):]

        if address.startswith(town):
            address = address[len(town):]

    # 全形數字轉半形
    address = fullwidth_to_halfwidth(address)

    return address


# =========================
# 單筆資料整理
# =========================
def normalize_store(store, city, town, town_id, query_type):
    city = normalize_tw_name(city)
    town = normalize_tw_name(town)

    raw = str(store.get("all", ""))
    tokens = {x.strip().lower() for x in raw.split(",") if x.strip()}

    has_toilet = ("toilet" in tokens) or ("wc" in tokens) or (query_type == "toilet")
    has_seat = ("rest" in tokens) or (query_type == "rest")
    has_powerbank = ("cs" in tokens) or (query_type == "cs")

    full_address = store.get("addr", "")
    store_location = clean_address(full_address, city, town)

    return {
        "town_id": town_id,
        "official_id": store.get("pkey", ""),
        "store_name": store.get("NAME", ""),
        "city": city,
        "town": town,
        "store_location": store_location,
        "store_latitude": store.get("py", ""),
        "store_longitude": store.get("px", ""),
        "TOILET": 1 if has_toilet else 0,
        "SEAT": 1 if has_seat else 0,
        "PBK": 1 if has_powerbank else 0
    }


# =========================
# 主程式
# =========================
def main():
    rows = []

    area_list, townid_map = load_areas_with_townid(FILE_PATH)

    for city, town in area_list:
        town_id = townid_map.get((city, town), "")

        for type_code, type_name in TYPE_MAP.items():
            print(f"抓取：{town_id} {city} {town} / {type_name}")

            stores = get_stores(city, town, type_code)

            if not stores:
                continue

            for store in stores:
                rows.append(
                    normalize_store(
                        store,
                        city,
                        town,
                        town_id,
                        type_code
                    )
                )

            time.sleep(0.12)

    if not rows:
        print("沒有抓到資料")
        return

    # 建立 DataFrame
    df = pd.DataFrame(rows)

    # 同門市不同服務合併
    agg_map = {
        "town_id": "first",
        "city": "first",
        "town": "first",
        "store_location": "first",
        "store_latitude": "first",
        "store_longitude": "first",
        "TOILET": "max",
        "SEAT": "max",
        "PBK": "max",
    }

    df = df.groupby(
        ["official_id", "store_name"],
        as_index=False
    ).agg(agg_map)

    # 欄位順序
    df = df[
        [
            "town_id",
            "official_id",
            "store_name",
            "city",
            "town",
            "store_location",
            "store_latitude",
            "store_longitude",
            "TOILET",
            "SEAT",
            "PBK"
        ]
    ]

    # 排序
    df.sort_values(
        by=["town_id", "official_id"],
        inplace=True
    )
    
    # 輸出 CSV
    TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M")
    filename = "familymart.csv"
    
    df.to_csv(
        "familymart.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n完成 ✅ 已輸出 {filename}，總共抓取 {len(df)} 間門市")


if __name__ == "__main__":
    main()