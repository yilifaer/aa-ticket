# aa-ticket 升级到 0.4.3（树莓派测试机）

适用于：已经装了 **0.4.2** 的 AA。这次**没有数据库变化**，只换代码和样式。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

0.4.2 测试报告第六节里决定要修的 14 项：

- 首页卡片：改派或转交后，原处理人的卡片马上刷新；每种语言单独缓存。
- 申请上级介入：第二次点时，总是提示「已经申请过 XX 介入了」；改请求里的部门编号问不出别的部门名字。
- 重新打开工单时，如果原处理人已经不能处理，工单直接回到「待接手」。
- 操作失败时不再留下没人用的图片文件；每天的清理任务也会删掉这类文件（只删一天以前的）。
- 「提交人补充内容」的频道提醒：没真正发出去就不占一小时一次的名额。
- 英文提示的单复数。
- 对比度：黄色「内部备注」「待接手」标记、灰色标签、紧急标记、「等你回复」、「接手」按钮、详情页右侧线框按钮，在 Flatly（浅色）和 Darkly（深色）主题下都达到 4.5:1。
- 西班牙语 Assignee 统一为「Responsable」；中文统一叫「申请上级介入」，自动触发的叫「自动申请上级介入」。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.3-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** `ls -lh ~/alliance_auth.bak-aa-ticket-0.4.3-*` 能看到文件，大小不是 0。

## 第 2 步：安装新版本

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@claude/friendly-einstein-21gzh0"
```

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.3`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

## 第 3 步：migrate、收集静态文件

```bash
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 显示 `No migrations to apply.`（这次没有新迁移，正常）；`collectstatic` 显示复制了文件（样式有改动）。

## 第 4 步：重启

```bash
exit
sudo supervisorctl restart myauth:
sudo supervisorctl status
```

**做完怎么确认：** 所有 `myauth:` 开头的进程都是 `RUNNING`。

> 这次样式改动多。打开页面后先按 `Ctrl + F5` 强制刷新一次，否则浏览器可能还在用旧样式。

---

## 第 5 步：检查

| # | 做什么 | 应该看到 |
|---|---|---|
| 1 | 任意插件页面看左上角 | `Tickets v0.4.3`（中文界面是 `工单 v0.4.3`） |
| 2 | 深色主题，打开一张有内部备注的工单 | 黄色「内部备注」标记是深色字，能看清；右侧「分配」「邀请协作」「移交」「修改紧急程度」「关闭工单」和「添加图片」的字都清楚 |
| 3 | 浅色主题，看同一张工单和部门管理页 | 灰色标签（部门名、「不接受玩家提交」）是深色字配浅灰底；「待接手」黄色标记是深色字 |
| 4 | 总览页 | 紧急工单的红色标记、「等你回复」标记、「接手」按钮的字都清楚 |
| 5 | 上级部门的人（或有「查看并处理所有工单」权限的人）接手一张下级部门的工单，再由该部门的人把它改派给别人 | 原处理人回到 AA 首页，「工单」卡片里马上没有这张工单了，不用等 30 秒 |
| 6 | Diplo 的工单（上级是 Leadership，Leadership 没有上级）：提交人连点两次「申请上级介入」 | 第二次提示「已经申请过 Leadership 介入了。」 |
| 7 | 处理人接手工单 → 提交人关闭 → 把处理人移出部门组 → 提交人重新打开 | 工单状态是「待接手」，没有处理人；同事能直接接手 |
| 8 | 把 Diplo 的 webhook 临时清掉 → 提交人在未接手的工单里回复 → 把 webhook 配回去 → 提交人再回复一次 | 配回去之后的那次回复，频道能收到提醒（之前会被「一小时一次」挡掉） |
| 9 | 界面切到英文，停用一个只剩 1 张未关闭工单的部门 | 提示是 `still has 1 open ticket.`（单数） |
| 10 | 中文界面：管理 → 紧急程度 | 列名和设置项写的是「自动申请上级介入」；总览里那一栏叫「申请上级介入或邀请协作的工单」；全站找不到「升级提醒」「上报」这两个词 |
| 11 | 界面切到西班牙语，打开工单详情 | 处理人一栏写的是 `Responsable` |
| 12 | 上传图片正常的回复 | 图片能显示、能打开（确认修图片清理没有影响正常上传） |

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

第 8 条测完记得确认 Diplo 的 webhook 已经配回去，并点一次「发送测试消息」。

---

## 出问题时退回 0.4.2（保留所有工单）

这次没有数据库变化，直接装回 0.4.2：

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@1b9eace"
cd /home/allianceserver/myauth
python manage.py collectstatic --noinput
exit
sudo supervisorctl restart myauth:
```

**做完怎么确认：** `pip show aa-ticket` 显示 `0.4.2`，工单都还在。
