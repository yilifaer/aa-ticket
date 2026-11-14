# 在树莓派（测试机）上安装 aa-ticket

这份说明写给第一次装 AA 插件的人。每一步都写了**做什么、在哪里做、做完怎么确认**。
先在树莓派上装好、测试没问题，再按同样的步骤装到正式服。

> 下面假设你的 AA 是按官方文档装的：
> - 用户：`allianceserver`
> - 虚拟环境：`/home/allianceserver/venv/auth/`
> - 项目目录：`/home/allianceserver/myauth/`
> - 用 supervisor 管理进程（进程组名 `myauth`）
>
> 如果你的路径不同，把命令里的路径换成你自己的。不确定的话，先执行第 0 步查一下。

---

## 第 0 步：确认路径和版本

**在哪里做：** 用 SSH 登录树莓派。

```bash
sudo su allianceserver
cd ~
ls
```

**做完怎么确认：** 能看到 `myauth` 和 `venv` 这两个文件夹。

接着进入虚拟环境，看 AA 版本：

```bash
source /home/allianceserver/venv/auth/bin/activate
pip show allianceauth | head -2
```

**做完怎么确认：** 显示 `Version: 5.4.0`。

---

## 第 1 步：备份数据库

**为什么：** 万一出问题，可以恢复回装插件之前的样子。

```bash
mysqldump -u root -p alliance_auth > ~/alliance_auth.bak-aa-ticket-$(date +%Y%m%d-%H%M).sql
```

（数据库名不一定叫 `alliance_auth`，在 `myauth/myauth/settings/local.py` 里的 `DATABASES` 可以看到。）

**做完怎么确认：**

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-*
```

能看到这个文件，并且大小不是 0。

---

## 第 2 步：安装插件

**在哪里做：** 还是在虚拟环境里（命令行开头有 `(auth)` 字样）。

```bash
pip install "git+https://github.com/yilifaer/aa-ticket.git@claude/friendly-einstein-21gzh0"
```

> 正式发布后，`@` 后面会换成版本号，比如 `@v0.1.0`。
> 如果仓库是私有的，树莓派没有权限拉取，就先在电脑上下载打包好的 `.whl` 文件，复制到树莓派后执行 `pip install 文件名.whl`。

**做完怎么确认：**

```bash
pip show aa-ticket | head -2
pip show allianceauth | head -2
```

- `aa-ticket` 显示版本 `0.1.0`；
- `allianceauth` **仍然是 5.4.0**（插件不会顺带升级 AA）。

---

## 第 3 步：修改 local.py

**在哪里做：**

```bash
nano /home/allianceserver/myauth/myauth/settings/local.py
```

改之前先备份：

```bash
cp /home/allianceserver/myauth/myauth/settings/local.py /home/allianceserver/myauth/myauth/settings/local.py.bak-aa-ticket-$(date +%Y%m%d-%H%M)
```

在文件**最后**加上下面这段：

```python
# ---- aa-ticket ----
INSTALLED_APPS += ["aa_ticket"]

MEDIA_ROOT = "/home/allianceserver/myauth/media/"

CELERYBEAT_SCHEDULE["aa_ticket_check_unclaimed"] = {
    "task": "aa_ticket.tasks.check_unclaimed",
    "schedule": crontab(minute="*/5"),
}
CELERYBEAT_SCHEDULE["aa_ticket_check_auto_close"] = {
    "task": "aa_ticket.tasks.check_auto_close",
    "schedule": crontab(minute="*/15"),
}
CELERYBEAT_SCHEDULE["aa_ticket_cleanup_attachments"] = {
    "task": "aa_ticket.tasks.cleanup_attachments",
    "schedule": crontab(minute=17, hour=3),
}
```

> 如果 `local.py` 里已经有 `MEDIA_ROOT`，就不要再加这一行。
> 如果文件里没有 `from celery.schedules import crontab`，在文件开头加上这一行。

按 `Ctrl + O` 保存，回车，再按 `Ctrl + X` 退出。

> **注意：** 不要让 nginx / Apache 直接对外提供这个 `media` 文件夹。图片只能通过插件自己带权限检查的页面查看。

然后创建图片文件夹：

```bash
mkdir -p /home/allianceserver/myauth/media
```

**做完怎么确认：**

```bash
cd /home/allianceserver/myauth
python manage.py check
```

最后一行显示 `System check identified ... issues`，并且里面**没有** `aa_ticket.W001`。

### 3.1 放宽上传大小（nginx）

nginx 默认只允许上传 1 MB，超过就会报错。打开 AA 的 nginx 配置：

```bash
sudo nano /etc/nginx/sites-available/allianceauth.conf
```

（文件名可能不同，`ls /etc/nginx/sites-available/` 可以看到。）在 `server {` 下面加一行：

```nginx
client_max_body_size 30m;
```

保存后检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

**做完怎么确认：** `nginx -t` 显示 `syntax is ok` 和 `test is successful`。

> 如果你们用的是 Apache，对应的设置是 `LimitRequestBody 31457280`。

---

## 第 4 步：建表、收集静态文件

```bash
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 的输出里有 `Applying aa_ticket.0001_initial... OK` 和 `Applying aa_ticket.0002_default_priorities... OK`。

---

## 第 5 步：重启 AA

先退出 `allianceserver` 用户（输入 `exit`），然后：

```bash
sudo supervisorctl restart myauth:
```

**做完怎么确认：**

```bash
sudo supervisorctl status
```

所有 `myauth:` 开头的进程都是 `RUNNING`。

---

## 第 6 步：给权限

**在哪里做：** 浏览器打开 AA → 右上角进入 **Admin（管理后台）**。

1. **所有成员都能提交工单：** Authentication → States → 打开 `Member` → Permissions 里加上
   `aa_ticket | general | Can submit and view own tickets` → 保存。
2. **管理员：** 给你自己所在的组加上 `aa_ticket | general | Can manage ticket settings`。
3. **（可选）联盟高层看所有工单：** 给高层的组加上 `Can view all tickets`。

**做完怎么确认：** 刷新 AA，左侧菜单出现「工单」。

---

## 第 7 步：建第一个部门

**在哪里做：** AA 左侧菜单 → 工单 → 顶部「管理」→ 部门 → 添加部门。

1. 名称填「外交」，简介写一句给玩家看的说明。
2. 「人员权限组」选外交人员所在的组（这个组要先在 AA 里建好）。
   **这个组必须是「不公开、不能自己申请」的组**，否则谁都能加进来看工单和内部备注。
3. Discord webhook：
   - 在 Discord 外交频道 → 编辑频道 → 整合 → Webhook → 新建 → 复制 Webhook URL；
   - 粘贴进来。
4. 要 @ 的 Discord 身份组 ID：
   - Discord 设置 → 高级 → 打开「开发者模式」；
   - 服务器设置 → 身份组 → 右键外交身份组 → 复制身份组 ID；
   - 粘贴进来。
5. 点「保存」，再进入这个部门，点「发送测试消息」。

**做完怎么确认：** Discord 外交频道收到一条「测试消息」。

---

## 第 8 步：完整测试一遍

用一个**不在外交组**的小号：

1. 工单 → 提交工单 → 选「外交」→ 紧急程度选 Urgent → 填标题和内容 → 提交。
   - ✅ Discord 外交频道收到新工单提醒，并 @ 了外交身份组。
2. 用外交人员的号打开这张工单 → 点「接手」→ 回复一句话。
   - ✅ 小号右上角铃铛收到通知；装了 aa-discordbot 的话，Discord 也收到私信。
3. 外交人员写一条「内部备注」。
   - ✅ 小号打开工单看不到这条备注。
4. 小号点「申请上级介入」（外交部门要先设了上级部门）。
   - ✅ 上级部门频道收到提醒。
5. 小号点「关闭工单」。
   - ✅ 工单状态变成「已关闭」，7 天内可以重新打开。

有任何一步不对，把现象截图发给我（**截图里不要带 webhook 地址**）。

---

## 出问题时怎么回滚

1. 从 `local.py` 删掉第 3 步加的那段（或者用备份文件恢复：把 `local.py.bak-aa-ticket-...` 复制回 `local.py`）。
2. 恢复数据库：
   ```bash
   mysql -u root -p alliance_auth < ~/alliance_auth.bak-aa-ticket-时间.sql
   ```
3. 卸载插件：
   ```bash
   pip uninstall aa-ticket
   ```
4. 重启：
   ```bash
   sudo supervisorctl restart myauth:
   ```

**做完怎么确认：** AA 能正常打开，左侧菜单没有「工单」。

---

## 以后升级

```bash
sudo su allianceserver
source /home/allianceserver/venv/auth/bin/activate
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@新版本号"
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
exit
sudo supervisorctl restart myauth:
```

升级前同样先做第 1 步的备份。
