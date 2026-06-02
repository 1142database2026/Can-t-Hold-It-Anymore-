"""
scripts/03_compare.py

功能：
  1. 讀取 02_merge_store.py 產出的 store_merged.csv
  2. 從 Supabase 撈取 store、store_service 現有資料
  3. 比對出新增 / 修改 / 刪除的差異
  4. 將差異序列化為 JSON，存入 diff_payload/ 供 deploy job 使用
  5. 產出 Markdown 報告渲染至 GitHub Actions Step Summary
  6. 若有異動，設定 output has_changes=true 讓 deploy job 啟動

環境變數（來自 GitHub Secrets）：
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY   ← 比對階段需要讀全表，用 service_role
"""

import os
import json
import pandas as pd
from supabase import create_client
from datetime import datetime

# ============================================================
# 設定
# ============================================================
MERGED_CSV   = "store_merged.csv"
PAYLOAD_DIR  = "diff_payload"
TIMESTAMP    = datetime.now().strftime("%Y%m%d%H%M")

SERVICE_MAP   = {1: "廁所", 2: "座位區", 3: "行動電源"}
SERVICE_COL   = {"TOILET": 1, "SEAT": 2, "PBK": 3}
BRAND_NAME    = {1: "7-ELEVEN", 2: "全家"}

# 比對 store 表時，這些欄位有差異才算「修改」
UPDATE_COLS = ["town_id", "store_location"]

os.makedirs(PAYLOAD_DIR, exist_ok=True)

# ============================================================
# Supabase 工具
# ============================================================
def get_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def fetch_all(supabase, table, select="*"):
    rows, offset, page_size = [], 0, 1000
    while True:
        res = (
            supabase.table(table)
            .select(select)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows.extend(res.data)
        if len(res.data) < page_size:
            break
        offset += page_size
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ============================================================
# 比對 store
# ============================================================
def diff_stores(store_df, db_df):
    """
    業務唯一鍵：(brand_id, official_id, store_name)
    回傳：
      to_insert  → list[dict]  完整的新門市資料
      to_update  → list[dict]  {store_id, changes}
      to_delete  → list[int]   store_id 清單
    """
    to_insert, to_update, to_delete = [], [], []

    # 建立舊資料索引
    db_index = {}
    if not db_df.empty:
        for _, row in db_df.iterrows():
            key = (str(row["brand_id"]), str(row["official_id"]), str(row["store_name"]))
            db_index[key] = row.to_dict()

    # 計算下一個 store_id（surrogate key 自行遞增）
    current_max_id = (
        int(db_df["store_id"].max()) + 1
        if not db_df.empty and "store_id" in db_df.columns
        else 1
    )

    csv_keys = set()
    for _, row in store_df.iterrows():
        key = (str(row["brand_id"]), str(row["official_id"]), str(row["store_name"]))
        csv_keys.add(key)

        if key not in db_index:
            # 新增
            to_insert.append({
                "store_id":        current_max_id,
                "brand_id":        int(row["brand_id"]),
                "official_id":     str(row["official_id"]),
                "store_name":      str(row["store_name"]),
                "town_id":         str(row.get("town_id", "")),
                "store_location":  str(row.get("store_location", "")),
                "store_latitude":  float(row["store_latitude"]) if pd.notna(row.get("store_latitude")) else None,
                "store_longitude": float(row["store_longitude"]) if pd.notna(row.get("store_longitude")) else None,
            })
            current_max_id += 1
        else:
            # 比較是否有欄位異動
            db_row = db_index[key]
            changes = {}
            for col in UPDATE_COLS:
                csv_val = str(row.get(col, "")).strip()
                db_val  = str(db_row.get(col, "")).strip()
                if csv_val != db_val:
                    changes[col] = {"old": db_val, "new": csv_val}
            if changes:
                to_update.append({
                    "store_id": int(db_row["store_id"]),
                    "brand_id": int(db_row["brand_id"]),
                    "official_id": str(db_row["official_id"]),
                    "store_name": str(db_row["store_name"]),
                    "changes": changes,
                })

    # 刪除：舊資料有但新資料沒有
    for key, db_row in db_index.items():
        if key not in csv_keys:
            to_delete.append({
                "store_id":   int(db_row["store_id"]),
                "brand_id":   int(db_row["brand_id"]),
                "official_id": str(db_row["official_id"]),
                "store_name": str(db_row["store_name"]),
            })

    return to_insert, to_update, to_delete


# ============================================================
# 比對 store_service
# ============================================================
def diff_services(merged_df, db_stores_df, db_svc_df):
    """
    merged_df 含 TOILET / SEAT / PBK 欄位
    比對後回傳應新增 / 應刪除的 (store_id, service_id) pairs
    """
    # (brand_id, official_id, store_name) -> store_id
    store_id_map = {}
    for _, row in db_stores_df.iterrows():
        key = (str(row["brand_id"]), str(row["official_id"]), str(row["store_name"]))
        store_id_map[key] = int(row["store_id"])

    # 計算「應有」的服務組合
    target = set()
    for _, row in merged_df.iterrows():
        key = (str(row["brand_id"]), str(row["official_id"]), str(row["store_name"]))
        store_id = store_id_map.get(key)
        if store_id is None:
            continue
        for col, svc_id in SERVICE_COL.items():
            if col in merged_df.columns:
                val = pd.to_numeric(row.get(col, 0), errors="coerce")
                if val == 1:
                    target.add((store_id, svc_id))

    # 現有服務組合
    existing = set()
    if not db_svc_df.empty:
        for _, row in db_svc_df.iterrows():
            existing.add((int(row["store_id"]), int(row["service_id"])))

    svc_to_insert = [{"store_id": s, "service_id": sv} for s, sv in (target - existing)]
    svc_to_delete = [{"store_id": s, "service_id": sv} for s, sv in (existing - target)]
    return svc_to_insert, svc_to_delete


# ============================================================
# 產出 GitHub Actions Step Summary（Markdown）
# ============================================================
def write_summary(to_insert, to_update, to_delete, svc_insert, svc_delete, db_stores_df):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/summary.md")

    # store_id → 描述 映射（方便報告顯示）
    id_info = {}
    if not db_stores_df.empty:
        for _, r in db_stores_df.iterrows():
            brand = BRAND_NAME.get(int(r["brand_id"]), "?")
            id_info[int(r["store_id"])] = f"[{brand}] {r['official_id']} {r['store_name']}"

    lines = []
    lines.append("# 🏪 門市資料同步比對報告\n")
    lines.append(f"> 執行時間：{TIMESTAMP}\n")

    # 總覽表格
    lines.append("## 📊 異動總覽\n")
    lines.append("| 資料表 | 新增 | 修改 | 刪除 |")
    lines.append("|--------|------|------|------|")
    lines.append(f"| `store` | **{len(to_insert)}** | **{len(to_update)}** | **{len(to_delete)}** |")
    lines.append(f"| `store_service` | **{len(svc_insert)}** | — | **{len(svc_delete)}** |")
    lines.append("")

    total = len(to_insert) + len(to_update) + len(to_delete) + len(svc_insert) + len(svc_delete)
    if total == 0:
        lines.append("## ✅ 無任何異動，資料庫與最新爬蟲結果完全一致！")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    # store 新增
    if to_insert:
        lines.append(f"## ✅ store 新增（{len(to_insert)} 筆）\n")
        lines.append("| store_id | brand | official_id | store_name | town_id |")
        lines.append("|----------|-------|-------------|------------|---------|")
        for r in to_insert[:50]:
            brand = BRAND_NAME.get(r["brand_id"], "?")
            lines.append(f"| {r['store_id']} | {brand} | {r['official_id']} | {r['store_name']} | {r['town_id']} |")
        if len(to_insert) > 50:
            lines.append(f"\n> ⚠️ 僅顯示前 50 筆，共 {len(to_insert)} 筆")
        lines.append("")

    # store 修改
    if to_update:
        lines.append(f"## ✏️ store 修改（{len(to_update)} 筆）\n")
        lines.append("| store_id | brand | official_id | store_name | 異動欄位 |")
        lines.append("|----------|-------|-------------|------------|----------|")
        for r in to_update[:50]:
            brand = BRAND_NAME.get(r["brand_id"], "?")
            changed_cols = ", ".join(r["changes"].keys())
            lines.append(f"| {r['store_id']} | {brand} | {r['official_id']} | {r['store_name']} | {changed_cols} |")
        if len(to_update) > 50:
            lines.append(f"\n> ⚠️ 僅顯示前 50 筆，共 {len(to_update)} 筆")
        lines.append("")

        # 修改細節（展開前 30 筆）
        lines.append("<details><summary>展開修改細節（前 30 筆）</summary>\n")
        lines.append("```json")
        lines.append(json.dumps(to_update[:30], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("</details>\n")

    # store 刪除
    if to_delete:
        lines.append(f"## 🗑️ store 刪除（{len(to_delete)} 筆）\n")
        lines.append("| store_id | brand | official_id | store_name |")
        lines.append("|----------|-------|-------------|------------|")
        for r in to_delete[:50]:
            brand = BRAND_NAME.get(r["brand_id"], "?")
            lines.append(f"| {r['store_id']} | {brand} | {r['official_id']} | {r['store_name']} |")
        if len(to_delete) > 50:
            lines.append(f"\n> ⚠️ 僅顯示前 50 筆，共 {len(to_delete)} 筆")
        lines.append("")

    # store_service 新增 / 刪除
    if svc_insert:
        lines.append(f"## ✅ store_service 新增（{len(svc_insert)} 筆）\n")
        lines.append("| store_id | 門市資訊 | 服務 |")
        lines.append("|----------|----------|------|")
        for r in svc_insert[:50]:
            info = id_info.get(r["store_id"], f"store_id={r['store_id']}")
            svc  = SERVICE_MAP.get(r["service_id"], r["service_id"])
            lines.append(f"| {r['store_id']} | {info} | {svc} |")
        if len(svc_insert) > 50:
            lines.append(f"\n> ⚠️ 僅顯示前 50 筆，共 {len(svc_insert)} 筆")
        lines.append("")

    if svc_delete:
        lines.append(f"## 🗑️ store_service 刪除（{len(svc_delete)} 筆）\n")
        lines.append("| store_id | 門市資訊 | 服務 |")
        lines.append("|----------|----------|------|")
        for r in svc_delete[:50]:
            info = id_info.get(r["store_id"], f"store_id={r['store_id']}")
            svc  = SERVICE_MAP.get(r["service_id"], r["service_id"])
            lines.append(f"| {r['store_id']} | {info} | {svc} |")
        if len(svc_delete) > 50:
            lines.append(f"\n> ⚠️ 僅顯示前 50 筆，共 {len(svc_delete)} 筆")
        lines.append("")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ Summary 已寫入：{summary_path}")


# ============================================================
# 主程式
# ============================================================
def main():
    print(f"{'='*50}")
    print(f"03_compare.py 開始執行：{TIMESTAMP}")
    print(f"{'='*50}")

    # --- 讀取爬蟲結果 ---
    merged_df = pd.read_csv(MERGED_CSV, encoding="utf-8-sig")
    print(f"  merged CSV：{len(merged_df)} 筆")

    # store 欄位（去掉 city / town / 服務旗標）
    drop_cols = [c for c in ["city", "town", "TOILET", "SEAT", "PBK"] if c in merged_df.columns]
    store_df  = merged_df.drop(columns=drop_cols)

    # --- 撈 Supabase ---
    print("\n從 Supabase 撈取現有資料...")
    supabase     = get_client()
    db_stores_df = fetch_all(supabase, "store")
    db_svc_df    = fetch_all(supabase, "store_service", "store_id, service_id")
    print(f"  store：{len(db_stores_df)} 筆")
    print(f"  store_service：{len(db_svc_df)} 筆")

    # --- 比對 ---
    print("\n比對中...")
    to_insert, to_update, to_delete = diff_stores(store_df, db_stores_df)

    # 新增的門市也要納入 service 比對（讓 deploy 時能建立對應 service）
    db_stores_with_new = (
        pd.concat([db_stores_df, pd.DataFrame(to_insert)], ignore_index=True)
        if to_insert else db_stores_df
    )
    svc_insert, svc_delete = diff_services(merged_df, db_stores_with_new, db_svc_df)

    total = len(to_insert) + len(to_update) + len(to_delete) + len(svc_insert) + len(svc_delete)
    print(f"\n  store     → 新增 {len(to_insert)}，修改 {len(to_update)}，刪除 {len(to_delete)}")
    print(f"  svc       → 新增 {len(svc_insert)}，刪除 {len(svc_delete)}")
    print(f"  總異動筆數：{total}")

    # --- 序列化差異 → diff_payload/ ---
    payload = {
        "timestamp":   TIMESTAMP,
        "store_insert": to_insert,
        "store_update": to_update,
        "store_delete": to_delete,
        "svc_insert":   svc_insert,
        "svc_delete":   svc_delete,
    }
    payload_path = os.path.join(PAYLOAD_DIR, "diff.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  diff payload 已儲存：{payload_path}")

    # --- GitHub Actions Summary ---
    write_summary(to_insert, to_update, to_delete, svc_insert, svc_delete, db_stores_df)

    # --- 設定 output 給 workflow 判斷是否啟動 deploy job ---
    has_changes = "true" if total > 0 else "false"
    github_output = os.environ.get("GITHUB_OUTPUT", "/tmp/github_output")
    with open(github_output, "a") as f:
        f.write(f"has_changes={has_changes}\n")
    print(f"\n  has_changes={has_changes}")
    print("\n✅ compare 完成！")


if __name__ == "__main__":
    main()
