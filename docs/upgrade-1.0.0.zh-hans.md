# aa-ticket 升级到 1.0.0（正式版）

适用于：已经装了 **0.4.7** 的 AA（树莓派测试机）。**1.0.0 和 0.4.7 的代码完全一样**，只改了版本号和说明文档，没有数据库变化。

从更早的测试版（0.x）升级，也照这份做，但要把对应版本升级说明里的检查一起做。旧的升级说明已经从仓库里删掉了，以 `CHANGELOG.md` 为准。

> 两种身份：
> - **你自己的账号**：能用 `sudo`。
> - **`allianceserver`**：`sudo su allianceserver` 切换过去；`exit` 回到自己的账号。

## 这次改了什么

- 版本号改成 `1.0.0`。
- 以后都用**版本号**安装（`@v1.0.0`），不再用开发分支名。开发分支已经删掉了。
- 安装说明 `docs/install-raspberry-pi.zh-hans.md` 里的安装、升级命令都改成了 `@v1.0.0`。

---

## 第 1 步：备份数据库

**在哪里做：** 你自己的账号。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-1.0.0-$(date +%Y%m%d-%H%M).sql
```

**做完怎么确认：** 运行下面这条，能看到文件，大小不是 0。

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-1.0.0-*
```

## 第 2 步：安装 1.0.0

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
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@v1.0.0"
```

**做完怎么确认：** `pip show aa-ticket | head -2` 显示 `1.0.0`；`pip show allianceauth | head -2` 仍是 `5.4.0`。

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
| 1 | 任意插件页面看左上角 | `Tickets v1.0.0`（中文界面是 `工单 v1.0.0`） |
| 2 | 提交一张工单，工作人员接手并回复 | 频道和私信照常收到，底部小字照常 |
| 3 | 上传一张手机照片 | 照常 |

代码和 0.4.7 一样，所以只要确认装上的是 1.0.0、一切照常就行。

---

## 装到正式服

测试机没问题后，正式服按 `docs/install-raspberry-pi.zh-hans.md` 从头装（第 0 步到第 8 步），安装命令已经是 `@v1.0.0`。
