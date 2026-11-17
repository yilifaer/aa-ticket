# aa-ticket 升级到 0.4.5（树莓派测试机）

适用于：已经装了 **0.4.3** 或 **0.4.4** 的 AA，直接装这一版就行，不用先装 0.4.4。这次**没有数据库变化**。只看这一份文档就够了：0.4.4 的检查项也合并进来了。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

### 0.4.4 的改动（从 0.4.3 升上来才是新的）

- 长边超过 4096 像素的图片按比例缩小到 4096 再保存，不再拒收；超过 1 亿像素才拒收。
- Discord 私信多了「部门」和「处理人」两栏。
- 所有时间都标「EVE」。
- 「分配」下拉框只列出能处理这张工单的人。
- 提示框、红色和灰色按钮用固定配色；右侧「关闭工单」是红字。
- 每天的图片清理更保守。

### 0.4.5 的改动

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

**下面这些是 0.4.4 的检查**（已经在 0.4.4 测过的可以跳过）：

| # | 做什么 | 应该看到 |
|---|---|---|
| 9 | 用 iPhone 原图（就是上次那张 24.5 MP 的），或者任何长边超过 4096 像素的图片，回复时上传 | 能上传成功；打开图片，长边是 4096 像素（电脑上右键「属性」或在手机相册里看尺寸）；照片里没有位置信息 |
| 10 | 上传一张长边不到 4096 像素的普通截图 | 尺寸不变 |
| 11 | （可选）上传一张超过 1 亿像素的图片（比如 12000 × 9000） | 提示「图片太大（12000 × 9000 像素）。最大支持 100 百万像素，请换一张更小的图片。」，回复没有发出去 |
| 12 | 让某张工单触发一次私信（比如工作人员回复提交人） | Discord 私信里，正文下面多了「部门」和「处理人」两栏；没人接手的工单「处理人」写「还没有」；私信里仍然没有回复内容 |
| 13 | 打开工单详情页 | 每条消息的时间、右侧「提交时间」（关闭的工单还有「已关闭」）都写成 `2026-11-16 23:11 EVE` 这样，不再有 `UTC` |
| 14 | 在总览页、工作台列表和 AA 首页的「工单」卡片上，把鼠标停在「x 分钟前」上 | 弹出的时间末尾是 `EVE` |
| 15 | 找一个在 Diplo 权限组里、但**没有** `aa_ticket.basic_access` 权限的号；用 Diplo 负责人打开一张 Diplo 工单点「分配」 | 下拉框里没有这个号。给他加上权限后（最多等 1 分钟）再打开，他就出现了 |
| 16 | 深色主题（Darkly）和浅色主题（Flatly）分别打开一张工单 | 右侧「关闭工单」是红字：浅色主题深红，深色主题浅红，都能看清；点开「关闭工单」弹窗，里面红色的确认按钮和灰色的「取消」按钮字都清楚，鼠标放上去、按 `Tab` 选中时也清楚 |
| 17 | 深色主题下打开一张快要自动关闭的工单（黄色提示框）、和一张已关闭的工单（灰色提示框）；AA 首页有紧急待接手时（红色提示框） | 提示框里的字都是深色字配浅色底，能看清 |
| 18 | 正常上传、查看图片 | 一切照常（确认清理改动没有影响正常图片） |

> 第 15 条：改了权限之后，首页卡片最多 30 秒、菜单上的数字最多 60 秒才会更新，这是缓存，正常。「分配」下拉框是每次打开页面重新算的，刷新一下就行。

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

---

## 出问题时退回原来的版本（保留所有工单）

这次没有数据库变化，直接装回原来的版本。下面是退回 **0.4.4** 的命令；如果你是从 **0.4.3** 升上来的，把第 4 条命令里 `@` 后面那一长串换成 `fcc2941bcf95f35977e860e6808d86abeb22883d`：

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

**做完怎么确认：** `pip show aa-ticket` 显示退回的版本号（`0.4.4` 或 `0.4.3`），工单都还在。
