---
name: git-commit-workflow
description: 專案內 Git commit 流程技能，要求先產出 dry commit 供確認，再在使用者明確同意後才執行真正 commit；適用於整理變更、撰寫 commit message、提交前確認格式與內容。
---

# Git Commit Workflow

## 何時使用

當使用者提到以下任一情境時啟用：

- `commit`、`提交`、`寫 commit message`
- `dry commit`、`先看訊息格式`
- `整理變更後再提交`
- 需要先確認 commit 內容與格式，再決定是否真的 commit

## 核心規則

1. 先做 `dry commit`，只輸出可提交的 commit 內容，不直接寫入 Git。
2. `dry commit` 必須先讓使用者確認：
   - 主標題
   - 中文條列摘要
3. 只有在使用者明確確認後，才執行真正的 `git add` / `git commit`。
4. commit message 以 conventional commits 風格為主，例如：
   - `feat(...)`
   - `fix(...)`
   - `chore(...)`
5. commit message 主標題後方要接中文條列，描述具體修改。
6. 不要加入 `重要問答` 這類額外段落。

## 執行流程

1. 先查看目前變更範圍，判斷這次 commit 應包含哪些檔案。
2. 整理成 `dry commit` 草稿，格式固定如下：
   - 第一行：`type(scope): summary`
   - 空一行
   - 下面用中文列點寫具體修改
3. 若變更範圍不明確，先縮小 commit 範圍，再產出 dry commit。
4. 等使用者確認後，再進入真正 commit。

## 輸出格式

`dry commit` 內容要維持這個樣式：

```text
feat(ui): add original holiday display for employee cells

- 新增「原始假日」切換，套用在每位員工的排班欄位。
- 日期列與星期列維持原本顯示，不改動表頭格子。
- 週六與國定假日在員工欄位顯示「休」。
- 週日在線上顯示「例」。
- 保留國定假日橘色標記與提示資訊。
- 切換選項後會即時重繪整張表。
```

## 注意事項

- 先確認再提交，不要預設直接 commit。
- 內容描述要具體，避免只寫「調整」、「修改」、「優化」這種空泛字眼。
- 若使用者要求訊息風格改變，優先遵守使用者當下要求，再維持這個 skill 的基本流程。
