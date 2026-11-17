# aa-ticket 升级到 0.4.5（树莓派测试机）

适用于：已经装了 **0.4.4** 的 AA。还是 0.4.3 的话，可以直接装这一版，然后把 0.4.4 升级文档第 5 步的检查也做一遍。这次**没有数据库变化**。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

每条 Discord 消息最下面都加了一行小字（消息卡片的页脚，小号灰色），固定英文：

```
This was a Ticket Bot Notice from 谁 to 谁 at 2026-11-15 11:03:28 EVE
```

- **from（谁发的）**：有人操作的写操作人的主角色名（回复、接手、改派、移交、邀请、关闭、重新打开、申请上级介入）；新工单和系统自动发的写 `Alliance Auth`（超时提醒、自动申请上级介入、自动关闭提醒、自动关闭）。
- **to（发给谁）**：发到部门频道的写部门名；私信写收信人的主角色名。
- **at（时间）**：事情发生的时间，EVE 时间，精确到秒。
- 频道消息、私信、管理页里的「发送测试消息」都有这一行。测试消息的 from 是点按钮的管理员。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.5-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** 运行下面这条，能看到文件，大小不是 0。

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-0.4.5-*
```

## 第 2 步：安装新版本

```bash
sudo su allianceserver
```

```bash
cd ~
```

```bash
source /home/allianceserver/venv/auth/bin/activate
```

```bash
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@claude/friendly-einstein-21gzh0"
```

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.5`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

## 第 3 步：migrate、收集静态文件

```bash
cd /home/allianceserver/myauth
```

```bash
python manage.py migrate
```

```bash
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 显示 `No migrations to apply.`（正常）。

## 第 4 步：重启

**一定要重启**，Celery 要用新代码发 Discord 消息。

```bash
exit
```

```bash
sudo supervisorctl restart myauth:
```

```bash
sudo supervisorctl status
```

**做完怎么确认：** 所有 `myauth:` 开头的进程都是 `RUNNING`。

---

## 第 5 步：检查

| # | 做什么 | 应该看到 |
|---|---|---|
| 1 | 任意插件页面看左上角 | `Tickets v0.4.5`（中文界面是 `工单 v0.4.5`） |
| 2 | 用一个普通玩家号提交一张 Diplo 的工单 | Diplo 频道的消息最下面有小字 `This was a Ticket Bot Notice from Alliance Auth to Diplo at …… EVE`，时间和提交时间对得上（EVE 时间） |
| 3 | Diplo 的人接手后回复玩家 | 玩家收到的私信最下面是 `…… from 回复人的主角色名 to 玩家的主角色名 at …… EVE` |
| 4 | 玩家回复 | 处理人收到的私信最下面是 `…… from 玩家的主角色名 to 处理人的主角色名 at …… EVE` |
| 5 | 把工单移交给另一个部门 | 新部门频道的消息写 `from 移交人的主角色名 to 新部门名` |
| 6 | 管理 → 部门 → Diplo → 发送测试消息 | 测试消息最下面写 `from 你的主角色名 to Diplo` |
| 7 | 中文频道语言下（管理 → 设置 → 频道语言选简体中文）再提交一张工单 | 消息正文是中文，最下面那行小字仍是英文 |
| 8 | （可选）等一张没人接手的工单触发超时提醒 | 提醒消息写 `from Alliance Auth` |

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

---

## 出问题时退回 0.4.4（保留所有工单）

这次没有数据库变化，直接装回 0.4.4：

```bash
sudo su allianceserver
```

```bash
cd ~
```

```bash
source /home/allianceserver/venv/auth/bin/activate
```

```bash
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@61d3c6c35dd2815d49896096aa94c1ffc2fbb141"
```

```bash
cd /home/allianceserver/myauth
```

```bash
python manage.py collectstatic --noinput
```

```bash
exit
```

```bash
sudo supervisorctl restart myauth:
```

**做完怎么确认：** `pip show aa-ticket` 显示 `0.4.4`，工单都还在。
