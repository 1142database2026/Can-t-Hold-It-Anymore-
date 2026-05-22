"""
scripts/04_deploy.py

功能：
  1. 讀取 03_compare.py 產出的 diff_payload/diff.json
  2. 依序執行：store 新增 → store 修改 → store_service 新增 → store_service 刪除 → store 刪除
     （順序重要：先建 store 才能建 store_service；先清 store_service 才能刪 store）
  3. 批次寫入（每批 500 筆），避免單次請求過大
  4. 輸出部署結果至 GitHub Actions Step Summary

環境變數（來自 GitHub Secrets）：
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
"""

import os
import json
from supabase import create_client
from datetime import datetime

# ============================================================
# 設定
# ============================================================
PAYLOAD_PATH = "diff_payload/diff.json"
BATCH_SIZE   = 500
TIMESTAMP    = datetime.now().strftime("%Y%m%d%H%M")
SERVICE_MAP  = {1: "廁所", 2: "座位區", 3: "行動電源"}
BRAND_NAME   = {1: "7-ELEVEN", 2: "全家"}

# ============================================================
# Supabase client
# ============================================================
def get_client():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# ============================================================
# 批次工具
# ============================================================
def batched(lst, size):
    """將 list 切成每批 size 筆的 generator"""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


# ============================================================
# 部署函式
# ============================================================
def deploy_store_insert(supabase, records):
    print(f"\n[store] 新增 {len(records)} 筆...")
    for i, batch in enumerate(batched(records, BATCH_SIZE)):
        supabase.table("store").insert(batch).execute()
        print(f"  批次 {i+1}：寫入 {len(batch)} 筆")
    print(f"  ✅ store 新增完成")


def deploy_store_update(supabase, records):
    print(f"\n[store] 修改 {len(records)} 筆...")
    for item in records:
        # 只更新有變動的欄位
        update_data = {col: v["new"] for col, v in item["changes"].items()}
        supabase.table("store").update(update_data).eq("store_id", item["store_id"]).execute()
    print(f"  ✅ store 修改完成")


def deploy_store_delete(supabase, records):
    """刪除 store 前 store_service 應已清除（呼叫順序保證）"""
    print(f"\n[store] 刪除 {len(records)} 筆...")
    ids = [r["store_id"] for r in records]
    for batch in batched(ids, BATCH_SIZE):
        supabase.table("store").delete().in_("store_id", batch).execute()
        print(f"  刪除 store_id：{batch[:5]}{'...' if len(batch)>5 else ''}")
    print(f"  ✅ store 刪除完成")


def deploy_svc_insert(supabase, records):
    print(f"\n[store_service] 新增 {len(records)} 筆...")
    for i, batch in enumerate(batched(records, BATCH_SIZE)):
        supabase.table("store_service").insert(batch).execute()
        print(f"  批次 {i+1}：寫入 {len(batch)} 筆")
    print(f"  ✅ store_service 新增完成")


def deploy_svc_delete(supabase, records):
    print(f"\n[store_service] 刪除 {len(records)} 筆...")
    for r in records:
        supabase.table("store_service").delete()\
            .eq("store_id", r["store_id"])\
            .eq("service_id", r["service_id"])\
            .execute()
    print(f"  ✅ store_service 刪除完成")


# ============================================================
# 部署結果寫入 Summary
# ============================================================
def write_deploy_summary(payload, success=True, error_msg=None):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "/tmp/summary.md")
    lines = []
    lines.append("# 🚀 部署結果報告\n")
    lines.append(f"> 執行時間：{TIMESTAMP}  |  來源資料時間戳：{payload.get('timestamp', 'N/A')}\n")

    if success:
        lines.append("## ✅ 部署成功！\n")
        lines.append("| 資料表 | 操作 | 筆數 |")
        lines.append("|--------|------|------|")
        lines.append(f"| `store` | 新增 | {len(payload['store_insert'])} |")
        lines.append(f"| `store` | 修改 | {len(payload['store_update'])} |")
        lines.append(f"| `store` | 刪除 | {len(payload['store_delete'])} |")
        lines.append(f"| `store_service` | 新增 | {len(payload['svc_insert'])} |")
        lines.append(f"| `store_service` | 刪除 | {len(payload['svc_delete'])} |")
    else:
        lines.append("## ❌ 部署失敗\n")
        lines.append(f"```\n{error_msg}\n```")

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ============================================================
# 主程式
# ============================================================
def main():
    print(f"{'='*50}")
    print(f"04_deploy.py 開始執行：{TIMESTAMP}")
    print(f"{'='*50}")

    # --- 讀取 diff payload ---
    if not os.path.exists(PAYLOAD_PATH):
        raise FileNotFoundError(f"找不到 diff payload：{PAYLOAD_PATH}")

    with open(PAYLOAD_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    store_insert = payload["store_insert"]
    store_update = payload["store_update"]
    store_delete = payload["store_delete"]
    svc_insert   = payload["svc_insert"]
    svc_delete   = payload["svc_delete"]

    total = len(store_insert) + len(store_update) + len(store_delete) + len(svc_insert) + len(svc_delete)
    print(f"  讀取 diff payload 完成，共 {total} 筆異動")
    print(f"  store     → 新增 {len(store_insert)}，修改 {len(store_update)}，刪除 {len(store_delete)}")
    print(f"  svc       → 新增 {len(svc_insert)}，刪除 {len(svc_delete)}")

    supabase = get_client()

    try:
        # ⚠️ 執行順序很重要：
        # 1. 先新增 store（後面的 svc 需要 store_id 存在）
        if store_insert:
            deploy_store_insert(supabase, store_insert)

        # 2. 修改 store
        if store_update:
            deploy_store_update(supabase, store_update)

        # 3. 新增 store_service（store 已存在）
        if svc_insert:
            deploy_svc_insert(supabase, svc_insert)

        # 4. 刪除 store_service（先清乾淨，才能刪 store）
        if svc_delete:
            deploy_svc_delete(supabase, svc_delete)

        # 5. 最後刪除 store（FK 已清除）
        if store_delete:
            deploy_store_delete(supabase, store_delete)

        print(f"\n🎉 全部部署完成！共處理 {total} 筆異動")
        write_deploy_summary(payload, success=True)

    except Exception as e:
        print(f"\n❌ 部署失敗：{e}")
        write_deploy_summary(payload, success=False, error_msg=str(e))
        raise   # 讓 GitHub Actions 標記為 failure


if __name__ == "__main__":
    main()
