# aa-ticket 升级到 0.4.1（树莓派测试机）

适用于：已经装了 **0.3.0** 的 AA（0.4.0 没有单独发布，直接升到 0.4.1）。这次有一个很小的数据库变化：给工单表加了 3 个索引（迁移 0005），不改动任何数据。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

- **新规则：先接手才能公开回复。** 只有提交人和当前处理人能公开回复；同部门同事、协助部门、上级部门、有「查看并处理所有工单」权限的人只能写内部备注，要回复得先「接手」或把工单改派给自己。关闭时附最终回复也只有提交人和处理人能用。
- 左上角「Tickets」旁显示版本号。
- 紧急工单只显示一个红色「紧急」标记，不管档位是什么颜色。
- 测试报告里的 5 个低级问题和全部可选建议。
- 整体审阅发现的问题（见 `CHANGELOG.md` 的 0.4.1 一节），例如：连点两次「申请上级介入」不会再一次升两级；回复被拒绝时，写好的文字不会丢；移交后不再跳到「页面不存在」。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.1-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** `ls -lh ~/alliance_auth.bak-aa-ticket-0.4.1-*` 能看到文件，大小不是 0。

## 第 2 步：安装新版本

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@claude/friendly-einstein-21gzh0"
```

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.1`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

## 第 3 步：migrate、收集静态文件

```bash
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 输出里有 `Applying aa_ticket.0005_ticket_indexes... OK`。

## 第 4 步：重启

```bash
exit
sudo supervisorctl restart myauth:
sudo supervisorctl status
```

**做完怎么确认：** 所有 `myauth:` 开头的进程都是 `RUNNING`。

> 浏览器里如果样式没变，按 `Ctrl + F5` 强制刷新一次（CSS 有改动）。

---

## 第 5 步：检查

准备：Sally 提交一张 Diplo 的工单。Diplo 现在有两个负责人：yilifaerr 和 Sally。另找一个只在 Diplo 组的号会更准；没有的话用 Sally 测「同事」，用另一个普通成员当提交人。

| # | 做什么 | 应该看到 |
|---|---|---|
| 1 | 任意插件页面看左上角 | `Tickets v0.4.1`（中文界面是 `工单 v0.4.1`），版本号是小一号的字 |
| 2 | 部门负责人打开一张**没人接手**的工单 | 回复框上方写「接手后才能回复提交人。」旁边有「接手」按钮；只能写内部备注，没有「回复」选项 |
| 3 | 点回复框旁的「接手」 | 工单变成处理中，回复框出现「回复 / 内部备注」两个选项 |
| 4 | 另一个负责人（同事）打开这张已接手的工单 | 回复框上方写「这张工单由 XX 处理，你可以写内部备注。」只能写内部备注 |
| 5 | 同事点「关闭工单」 | 弹窗里没有「最终回复」输入框，只问「关闭这张工单？」；能关闭 |
| 6 | 处理人点「关闭工单」 | 弹窗里有「最终回复（选填）」 |
| 7 | 用「分配」把工单改派给同事 | 同事能公开回复了，原处理人只能写内部备注 |
| 8 | 提交人在工单里回复 | 和以前一样，随时能回复（关闭后除外） |
| 9 | yilifaerr（有「查看并处理所有工单」权限）打开别人处理的工单 | 也只能写内部备注 |
| 10 | 总览 / 首页卡片里的紧急工单 | 只有一个红色「Urgent」标记，没有重复 |
| 11 | 深色主题下打开有内部备注的工单 | 内部备注的标题栏（名字、时间）能看清 |
| 12 | 手机宽度打开总览 | 「接手」「查看全部」按钮够大，好点 |
| 13 | 管理 → 部门 | 「不接受玩家提交」标签在深色主题下能看清；上级停用时，下级不缩进，并写着「上级：XX（已停用）」 |
| 14 | 员工打开 AA 首页 | 「工单」卡片里，自己没有提交的工单时，不再显示「我的未关闭工单: 0」「等你回复: 0」 |

| 15 | 协作部门的人打开被邀请的工单 | 提示「你的部门在协助这张工单，可以写内部备注；回复提交人由负责部门来做。」，没有「接手」按钮 |
| 16 | 回复时附一个不是图片的文件 | 报错，但回复框里写好的文字还在 |
| 17 | 把工单移交给别的部门，并取消勾选「原部门继续协作」 | 跳到工作台，提示「工单已移交。」，不是「页面不存在」 |
| 18 | 提交人连点两次「申请上级介入」 | 只升一级；第二次提示「已经申请过 XX 介入了。」 |

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

---

## 出问题时退回 0.3.0（保留所有工单）

先把数据库退回 0.3.0 的结构（只是去掉 3 个索引），再装回 0.3.0：

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
cd /home/allianceserver/myauth
python manage.py migrate aa_ticket 0004
cd ~
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@3a11505"
cd /home/allianceserver/myauth
python manage.py collectstatic --noinput
exit
sudo supervisorctl restart myauth:
```

**做完怎么确认：** `pip show aa-ticket` 显示 `0.3.0`，工单都还在。
