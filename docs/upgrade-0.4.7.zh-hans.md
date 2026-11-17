# aa-ticket 升级到 0.4.7（树莓派测试机）

适用于：已经装了 **0.4.6** 的 AA。这次**没有数据库变化**。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

0.4.6 测试报告第 7 节的决定：

- **动图总量也降到 2500 万像素**：GIF、WEBP 动图的「帧数 × 宽 × 高」最多 2500 万像素（以前是 1 亿）。超过时会提示是动图总量太大，并写出帧数和每帧尺寸，告诉对方减少帧数或缩小尺寸。中文提示：「这个动图总量太大（4 帧，每帧 5000 × 5000 像素）。所有帧加起来最多 25 百万像素，请减少帧数或缩小尺寸。」
- **文档**：0.4.6 升级文档里停、启 Celery 的命令改成了 `myauth:worker_00`。这次检查不需要停 Celery。

另外修了一个跟着上面那条出现的问题：

- **手机照片不会被当成动图**：很多手机照片（安卓 Ultra HDR、iPhone 的 HDR 照片、带景深的人像照片）里面除了主图还藏着一张小的辅助图，会被读成「2 帧」。如果只降动图上限，普通的 1200 万像素手机照片也会被拒。现在只有 GIF 和 WEBP 才按动图算总量；这类照片只保存主图，所以只看主图是不是超过 2500 万像素。动态 PNG 也一样，只保存第一帧（以前就是这样）。

插件里别的地方都没有改。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-0.4.7-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** 运行下面这条，能看到文件，大小不是 0。

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-0.4.7-*
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

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `0.4.7`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

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
| 1 | 任意插件页面看左上角 | `Tickets v0.4.7`（中文界面是 `工单 v0.4.7`） |
| 2 | 上传 5000 × 5000、4 帧的 WEBP 动图（就是上次那张） | 被拒收，中文提示「这个动图总量太大（4 帧，每帧 5000 × 5000 像素）。所有帧加起来最多 25 百万像素，请减少帧数或缩小尺寸。」，回复没有发出去，文字还在框里 |
| 3 | 同样 5000 × 5000、4 帧的 GIF 动图 | 同样被拒收，提示一样 |
| 4 | 3000 × 3000、11 帧的 WEBP 动图（约 9900 万像素） | 被拒收（以前能传） |
| 5 | 480 × 270、100 帧的普通动图（约 1300 万像素） | 能上传，能播放，帧数不变 |
| 6 | 上传一张普通照片和一张截图 | 照常 |
| 6b | 用手机**原图**上传：安卓手机开着 HDR 拍的照片，或 iPhone 拍的照片（从手机直接传，不要截图） | 能上传成功，保存后是普通 JPEG，长边超过 4096 的缩到 4096 |
| 7 | 英文界面重复第 2 条 | 英文提示 `This animation is too large in total (4 frames of 5000 × 5000 pixels). All frames together may have up to 25 megapixels. Use fewer frames or a smaller size.` |

哪一条不对，记下编号、现象和截图发给我。

---

## 出问题时退回 0.4.6（保留所有工单）

这次没有数据库变化，直接装回 0.4.6：

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
pip install --force-reinstall --no-deps "git+https://github.com/yilifaer/aa-ticket.git@253004bf0cda536c4093887d1fe8c0059c28f385"
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

**做完怎么确认：** `pip show aa-ticket` 显示 `0.4.6`，工单都还在。
