# aa-ticket 升级到 0.4.4（树莓派测试机）

适用于：已经装了 **0.4.3** 的 AA。这次**没有数据库变化**，只换代码、样式和翻译。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

0.4.3 测试报告第五、六节里决定要做的：

- **大图片不再拒收**：长边超过 4096 像素的图片，按比例缩小到长边 4096 像素再保存（照片里的位置等信息照样去掉）。只有超过 1 亿像素的图片才拒收，提示里会写明上限，让换一张更小的。
- **Discord 私信**多了「部门」和「处理人」两栏（没人接手时写「还没有」），仍然不带回复正文。
- **所有时间都标「EVE」**（EVE 时间就是 UTC）：消息时间、右侧「提交时间」「已关闭」、列表和首页卡片上鼠标悬停显示的时间、部门页上「最近一次发送失败」的时间。
- **「分配」下拉框**只列出能处理这张工单的人（账号有效、有 `aa_ticket.basic_access` 权限、在负责部门里）；不满足的人也不能被分配。
- **固定配色**：黄色、红色、灰色、蓝色提示框，红色和灰色按钮，在插件页面和 AA 首页的「工单」卡片里都改用固定配色，五套主题下静止、悬停、键盘选中都在 6:1 以上（要求 4.5:1）。
- **右侧「关闭工单」按钮的字是红色**：浅色主题深红，深色主题浅红。
- **每天的图片清理更保守**：只在图片存在本机硬盘时运行；`media/aa_ticket` 是链接（快捷方式）时跳过；只删插件自己起名的图片文件（32 位十六进制加图片后缀），链接文件不碰。
- **文档**：写明改权限后首页卡片最多 30 秒、菜单数字最多 60 秒才更新。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.4-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** 运行下面这条，能看到文件，大小不是 0。

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-0.4.4-*
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

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.4`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

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

**做完怎么确认：** `migrate` 显示 `No migrations to apply.`（这次没有新迁移，正常）；`collectstatic` 显示复制了文件（样式有改动）。

## 第 4 步：重启

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

> 样式有改动。打开页面后先按 `Ctrl + F5` 强制刷新一次，否则浏览器可能还在用旧样式。

---

## 第 5 步：检查

| # | 做什么 | 应该看到 |
|---|---|---|
| 1 | 任意插件页面看左上角 | `Tickets v0.4.4`（中文界面是 `工单 v0.4.4`） |
| 2 | 用 iPhone 原图（就是上次那张 24.5 MP 的），或者任何长边超过 4096 像素的图片，回复时上传 | 能上传成功；打开图片，长边是 4096 像素（电脑上右键「属性」或在手机相册里看尺寸）；照片里没有位置信息 |
| 3 | 上传一张长边不到 4096 像素的普通截图 | 尺寸不变 |
| 4 | （可选）上传一张超过 1 亿像素的图片（比如 12000 × 9000） | 提示「图片太大（12000 × 9000 像素）。最大支持 100 百万像素，请换一张更小的图片。」，回复没有发出去 |
| 5 | 让某张工单触发一次私信（比如工作人员回复提交人） | Discord 私信里，正文下面多了「部门」和「处理人」两栏；没人接手的工单「处理人」写「还没有」；私信里仍然没有回复内容 |
| 6 | 打开工单详情页 | 每条消息的时间、右侧「提交时间」（关闭的工单还有「已关闭」）都写成 `2026-11-16 23:11 EVE` 这样，不再有 `UTC` |
| 7 | 在总览页、工作台列表和 AA 首页的「工单」卡片上，把鼠标停在「x 分钟前」上 | 弹出的时间末尾是 `EVE` |
| 8 | 找一个在 Diplo 权限组里、但**没有** `aa_ticket.basic_access` 权限的号；用 Diplo 负责人打开一张 Diplo 工单点「分配」 | 下拉框里没有这个号。给他加上权限后（最多等 1 分钟）再打开，他就出现了 |
| 9 | 深色主题（Darkly）和浅色主题（Flatly）分别打开一张工单 | 右侧「关闭工单」是红字：浅色主题深红，深色主题浅红，都能看清；点开「关闭工单」弹窗，里面红色的确认按钮和灰色的「取消」按钮字都清楚，鼠标放上去、按 `Tab` 选中时也清楚 |
| 10 | 深色主题下打开一张快要自动关闭的工单（黄色提示框）、和一张已关闭的工单（灰色提示框）；AA 首页有紧急待接手时（红色提示框） | 提示框里的字都是深色字配浅色底，能看清 |
| 11 | 正常上传、查看图片 | 一切照常（确认清理改动没有影响正常图片） |

哪一条不对，记下编号、现象和截图发给我（截图里不要带 webhook 地址）。

> 第 8 条：改了权限之后，首页卡片最多 30 秒、菜单上的数字最多 60 秒才会更新，这是缓存，正常。「分配」下拉框是每次打开页面重新算的，刷新一下就行。

---

## 出问题时退回 0.4.3（保留所有工单）

这次没有数据库变化，直接装回 0.4.3：

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
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@fcc2941bcf95f35977e860e6808d86abeb22883d"
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

**做完怎么确认：** `pip show aa-ticket` 显示 `0.4.3`，工单都还在。
