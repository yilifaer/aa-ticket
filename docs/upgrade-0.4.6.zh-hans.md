# aa-ticket 升级到 0.4.6（树莓派测试机）

适用于：已经装了 **0.4.5** 的 AA。这次**没有数据库变化**。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

0.4.5 测试报告第 7 节的三条决定：

- **图片上限改回 2500 万像素**，JPEG、PNG、WEBP、GIF 都一样。2500 万像素以内、长边超过 4096 的照样缩到 4096 再保存。拒收提示里的数字变成 25。4800 万像素模式拍的照片会被拒收（你已经确认接受）。
- **Discord 消息里的「部门」「处理人」记的是事情发生那一刻的**，不再等到真正发出时才去查。频道消息里的「部门」、移交提示里的部门名，私信里的「部门」「处理人」、「工单已移交给 ……」都是这样。升级那一刻还在排队的旧消息照旧按当前状态。
- **黄色「将自动关闭」提示**：鼠标放上去显示具体时间，例如 `2026-11-24 00:48 EVE`。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.6-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** 运行下面这条，能看到文件，大小不是 0。

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-0.4.6-*
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

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.6`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

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
| 1 | 任意插件页面看左上角 | `Tickets v0.4.6`（中文界面是 `工单 v0.4.6`） |
| 2 | 上传一张 2500 万像素以上的图片（比如 6000 × 5000 的 PNG，或 4800 万像素模式拍的照片） | 被拒收，中文提示「图片太大（6000 × 5000 像素）。最大支持 25 百万像素，请换一张更小的图片。」，回复没有发出去 |
| 3 | 上传一张 iPhone 普通照片（比如 4284 × 5712，约 2450 万像素） | 能上传，长边缩到 4096 |
| 4 | 上传一张普通截图 | 尺寸不变 |
| 5 | 先停掉 Celery（命令见下面），提交人在一张 Diplo 工单里回复；再把这张工单移交给 FC；然后启动 Celery | 处理人收到的私信里，「部门」是 **Diplo**、「处理人」是原来的处理人（回复那一刻的状态），不是 FC |
| 6 | 打开一张「等提交人回复」的工单（会出现黄色「将自动关闭」提示），鼠标放在那句话上 | 弹出具体时间，例如 `2026-11-24 00:48 EVE` |
| 7 | 正常提交工单、回复 | 频道和私信照常收到，底部小字照常 |

第 5 条停、启 Celery 的命令（在你自己的账号下）：

```bash
sudo supervisorctl stop myauth:worker_00
```

```bash
sudo supervisorctl start myauth:worker_00
```

> 你那边 Celery 进程的名字如果不叫 `myauth:worker_00`，先用 `sudo supervisorctl status` 看一下，用列表里带 `worker` 的那个名字。第 5 条测完一定要确认它又是 `RUNNING`。

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

---

## 出问题时退回 0.4.5（保留所有工单）

这次没有数据库变化，直接装回 0.4.5：

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
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@cdcde328580934dbfb656e0204bb62e04574898f"
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

**做完怎么确认：** `pip show aa-ticket` 显示 `0.4.5`，工单都还在。
