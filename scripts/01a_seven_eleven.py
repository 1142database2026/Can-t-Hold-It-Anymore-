import requests
import xml.etree.ElementTree as ET
import pandas as pd
import random
import time
from datetime import datetime

file_path = "taiwan_area.xlsx"
BASE_URL = "https://emap.pcsc.com.tw/EMapSDK.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# =========================
# 1️⃣ 讀取 Excel (同時讀取 town_id)
# =========================
def load_areas_with_townid(file_path):
    print("正在讀取行政區與id對照表:", file_path)

    df = pd.read_excel(file_path, engine="openpyxl")

    areas_info = []
    townid_mapping = {}

    for _, row in df.iterrows():
        city = str(row["city"]).strip()
        town = str(row["town"]).strip()
        town_id = str(row["town_id"]).strip()

        areas_info.append((city, town))
        townid_mapping[(city, town)] = town_id

    return areas_info, townid_mapping


# =========================
# 2️⃣ 清理地址
# =========================
def clean_address(address, city, town):
    if address.startswith(city + town):
        return address[len(city + town):]

    elif address.startswith(city):
        return address[len(city):]

    return address


# =========================
# 3️⃣ 抓門市
# =========================
def get_stores_by_town(city, town, town_id):
    data = {
        "commandid": "SearchStore",
        "city": city,
        "town": town
    }

    try:
        res = requests.post(BASE_URL, data=data, headers=HEADERS, timeout=10)
        res.encoding = "utf-8"
        root = ET.fromstring(res.text)

    except Exception as e:
        print(f"連線錯誤 {city}{town}: {e}")
        return []

    stores = []

    for store in root.findall(".//GeoPosition"):
        official_id = store.find("POIID").text if store.find("POIID") is not None else ""

        store_name = (
            "7-ELEVEN " + store.find("POIName").text + "門市"
            if store.find("POIName") is not None else ""
        )

        address = store.find("Address").text if store.find("Address") is not None else ""

        loc = clean_address(address, city, town)

        service = (
            store.find("StoreImageTitle").text
            if store.find("StoreImageTitle") is not None else ""
        )

        service_text = service or ""

        # 經緯度處理
        x = store.find("X").text if store.find("X") is not None else None
        y = store.find("Y").text if store.find("Y") is not None else None

        try:
            lng = float(x)
            lat = float(y)

            if lng > 1000:
                lng /= 1000000

            if lat > 1000:
                lat /= 1000000

        except:
            lng = None
            lat = None

        # 服務判斷
        has_toilet = "02廁所" in service_text
        has_seat = "04座位區" in service_text
        has_powerbank = "12行動電源租賃" in service_text

        stores.append({
            "town_id": town_id,
            "official_id": official_id,
            "store_name": store_name,
            "city": city,
            "town": town,
            "loc": loc,
            "lat": lat,
            "lng": lng,
            "TOILET": 1 if has_toilet else 0,
            "SEAT": 1 if has_seat else 0,
            "PBK": 1 if has_powerbank else 0
        })

    return stores


# =========================
# 4️⃣ 抓全台
# =========================
def get_all_stores(area_list, townid_mapping):
    all_stores = []

    for city, town in area_list:
        town_id = townid_mapping.get((city, town), "")

        try:
            stores = get_stores_by_town(city, town, town_id)
            all_stores.extend(stores)

            print(f"完成：{town_id} {city} {town} ({len(stores)} 間)")
            time.sleep(random.uniform(0.1, 0.3))

        except Exception as e:
            print(f"錯誤：{city} {town} → {e}")

    return all_stores


# =========================
# 5️⃣ 篩選資料
# =========================
def filter_stores(stores):
    return [
        s for s in stores
        if s["TOILET"] or s["SEAT"] or s["PBK"]
    ]


# =========================
# 6️⃣ 輸出 CSV
# =========================
def export_to_csv(stores, output_file="result.csv"):
    if not stores:
        print("沒有資料可以匯出")
        return

    df = pd.DataFrame(stores)

    columns_order = [
        "town_id",
        "official_id",
        "store_name",
        "city",
        "town",
        "loc",
        "lat",
        "lng",
        "TOILET",
        "SEAT",
        "PBK"
    ]

    df = df[columns_order]

    df.columns = [
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

    df.sort_values(by=["town_id", "official_id"],inplace=True)

    df.drop_duplicates(subset=["official_id"], inplace=True)

    df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig"
    )

    print(f"\n已成功輸出 CSV：{output_file}")


# =========================
# 主程式
# =========================
if __name__ == "__main__":
    TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M")

    areas, townid_map = load_areas_with_townid(file_path)

    all_data = get_all_stores(areas, townid_map)

    filtered_data = filter_stores(all_data)

    export_to_csv(filtered_data, "seven_eleven.csv")
