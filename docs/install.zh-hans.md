# aa-ticket 安装步骤

这份说明写给第一次装 AA 插件的人。每一步都写了**做什么、在哪里做、做完怎么确认**。
有测试机的话，建议先在测试机上装好、测试没问题，再按同样的步骤装到正式服。

**已经装过旧版本？** 直接看最后的「[升级](#升级)」。

> 下面假设你的 AA 是按官方文档装的：
> - 用户：`allianceserver`
> - 虚拟环境：`/home/allianceserver/venv/auth/`
> - 项目目录：`/home/allianceserver/myauth/`
> - 用 supervisor 管理进程（进程组名 `myauth`）
>
> 如果你的路径不同，把命令里的路径换成你自己的。不确定的话，先执行第 0 步查一下。

> **两种身份，别搞混：**
> - **你自己的账号**：能用 `sudo`，用来改 nginx、重启服务、备份数据库。
> - **`allianceserver`**：用 `sudo su allianceserver` 切换过去，用来装插件、改 `local.py`、执行 `manage.py`。这个账号**不能**用 `sudo`。要回到自己的账号，输入 `exit`。

---

## 第 0 步：确认路径和版本

**在哪里做：** 用 SSH 登录 AA 所在的服务器，然后切换到 `allianceserver`：

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

**做完怎么确认：** 显示 `Version: 5.0.0` 或更高。

> AA 5.0 和 5.1 还要再装一个旧版的 django-sri：`pip install "django-sri<1"`。新版 django-sri 会让这两个 AA 版本自己的页面出错。

---

## 第 1 步：备份数据库

**为什么：** 万一出问题，可以恢复回装插件之前的样子。

**在哪里做：** 用**你自己的账号**（如果还在 `allianceserver` 里，先输入 `exit`）。

```bash
sudo mysqldump alliance_auth > ~/alliance_auth.bak-aa-ticket-$(date +%Y%m%d-%H%M).sql
```

> 数据库名不一定叫 `alliance_auth`，在 `myauth/myauth/settings/local.py` 里的 `DATABASES` 可以看到。
> 如果你的 MySQL root 需要密码，把 `sudo mysqldump` 换成 `mysqldump -u root -p`。

**做完怎么确认：**

```bash
ls -lh ~/alliance_auth.bak-aa-ticket-*
```

能看到这个文件，并且大小不是 0。

---

## 第 2 步：安装插件

**在哪里做：** 切换到 `allianceserver`，**先 `cd ~`**，再进入虚拟环境：

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install "git+https://github.com/yilifaer/aa-ticket.git@v1.0.1"
```

> 一定要先 `cd ~`。如果当前所在的文件夹 `allianceserver` 没有权限读，pip 会报 `PermissionError: __editable__...`。
> `@` 后面是版本号。以后出了新版本，换成新的版本号就行。

**做完怎么确认：**

```bash
pip show aa-ticket | head -2
pip show allianceauth | head -2
```

- `aa-ticket` 显示版本 `1.0.1`；
- `allianceauth` **和装之前的版本一样**（插件不会顺带升级 AA）。

---

## 第 3 步：修改 local.py

**在哪里做：** 还是 `allianceserver`。改之前先备份：

```bash
cp /home/allianceserver/myauth/myauth/settings/local.py /home/allianceserver/myauth/myauth/settings/local.py.bak-aa-ticket-$(date +%Y%m%d-%H%M)
nano /home/allianceserver/myauth/myauth/settings/local.py
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

然后创建图片文件夹：

```bash
mkdir -p /home/allianceserver/myauth/media
```

> **注意：** 不要让 nginx / Apache 直接对外提供这个 `media` 文件夹。图片只能通过插件自己带权限检查的页面查看。

**做完怎么确认：**

```bash
cd /home/allianceserver/myauth
python manage.py check
```

输出里**没有** `aa_ticket.W001`、`aa_ticket.W002`（图片文件夹没设置、不存在或不能写）、`aa_ticket.W003`（上面 3 个定时任务少了哪个，它会写出来）和 `aa_ticket.W004`（没设 `SITE_URL`，Discord 里的链接会打不开；AA 的 `local.py` 一般已经设好了）。

---

## 第 4 步：建表、收集静态文件

**在哪里做：** 还是 `allianceserver`，在项目目录里：

```bash
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
```

**做完怎么确认：** `migrate` 的输出里有 `Applying aa_ticket.0001_initial... OK`、`0002_default_priorities... OK`、`0003_language_settings_and_view_all_name... OK`、`0004_priority_is_urgent... OK`、`0005_ticket_indexes... OK`、`0006_submit_restriction_and_hourly_limit... OK`。

---

## 第 5 步：放宽上传大小、检查私信路由、重启

这一步要用 `sudo`，所以先回到**你自己的账号**：

```bash
exit
```

### 5.1 放宽上传大小（nginx）

nginx 默认只允许上传 1 MB。打开 AA 的 nginx 配置（文件名可能不同，`ls /etc/nginx/sites-available/` 可以看到）：

```bash
sudo nano /etc/nginx/sites-available/allianceauth.conf
```

按 `Ctrl + W` 搜索 `client_max_body_size`：

- **找到了**：把后面的数字改成 `32m`，比如 `client_max_body_size 32m;`。
- **没找到**：在 `server {` 下面加一行 `client_max_body_size 32m;`。

> 32m 刚好够一次回复传 5 张最大尺寸（每张 6 MB）的图片。

> 同一个 `server` 里不能写两行 `client_max_body_size`，否则 nginx 会报错。

保存后检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

**做完怎么确认：** `nginx -t` 显示 `syntax is ok` 和 `test is successful`。

> 如果你们用的是 Apache，对应的设置是 `LimitRequestBody 31457280`。

### 5.2 检查 Discord 私信路由（装了 aa-discordbot 才需要）

aa-discordbot 要求 `myauth/myauth/celery.py` 里有一条路由，**缺了它所有插件的私信都发不出去**（worker 日志里会报 `This function should be called asynchronously`）。

```bash
sudo grep -n "aadiscordbot" /home/allianceserver/myauth/myauth/celery.py
```

- **能看到** `"aadiscordbot.tasks.*": {"queue": "aadiscordbot"}`：没问题，跳过。
- **看不到**：按 aa-discordbot 官方说明把这条路由加进 `celery.py`（改之前先备份成 `celery.py.bak-aa-ticket-时间`）。

### 5.3 重启 AA

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

**在哪里做：** 浏览器打开 AA → 右上角进入 **Admin（管理后台）**。权限在列表里显示为 `Tickets | general | ...`。

1. **所有成员都能提交工单：** Authentication → States → 打开 `Member` → Permissions 里加上
   `Tickets | general | Can submit and view own tickets` → 保存。
2. **部门人员和管理员也要有上面这条权限**，否则他们打不开工单页面。
3. **管理员：** 给你自己所在的组再加上 `Tickets | general | Can manage ticket settings`。这个权限能决定谁看哪些工单，只给信得过的一两个人。
4. **（可选）联盟高层看并处理所有工单：** 给高层的组加上 `Tickets | general | Can view and handle all tickets`。

> 第 3、4 条的组也必须有第 1 条的 `Can submit and view own tickets`，否则这些人看不到插件。这些组要设成不公开、不能自己申请（Internal）。

**做完怎么确认：** 刷新 AA，左侧菜单出现「工单」。

> 以后改了权限或权限组，AA 首页的「工单」卡片最多要 30 秒、左侧菜单上的数字最多要 60 秒才会跟着变，这是缓存造成的，正常。工单页面本身每次打开都会重新检查权限。

---

## 第 7 步：建第一个部门和设置语言

**在哪里做：** AA 左侧菜单 → 工单 → 顶部「管理」。

### 7.1 部门

「部门」→「添加部门」：

1. 名称填部门名，比如「外交」；简介写一句给玩家看的说明。下面都以「外交」为例。
2. 「人员权限组」选外交人员所在的组（这个组要先在 AA 里建好）。
   **这个组必须是「不公开、不能自己申请」的组**（在 AA 后台把组设成 Internal），否则谁都能加进来看工单和内部备注。设置错了，部门列表里会出现红色警告。
3. Discord webhook：
   - 在 Discord 外交频道 → 编辑频道 → 整合 → Webhook → 新建 → 复制 Webhook URL；
   - 粘贴进来。
4. 要 @ 的 Discord 身份组 ID：
   - Discord 设置 → 高级 → 打开「开发者模式」；
   - 服务器设置 → 身份组 → 右键外交身份组 → 复制身份组 ID；
   - 粘贴进来。
5. 点「保存」，再进入这个部门，点「发送测试消息」。

**做完怎么确认：** Discord 外交频道收到一条「测试消息」。

### 7.2 语言

「设置」里有两项：

- **Discord 频道消息的语言**：默认英文。所有部门频道的提醒都用这种语言。
- **Discord 私信的语言**：默认「每个人自己的语言」，也可以改成「和频道用同一种语言」。

> AA 铃铛通知和「每个人自己的语言」取的是每个人**个人资料里的语言**，不是网页右上角临时切换的语言。

**做完怎么确认：** 改完点保存，再到部门里点「发送测试消息」，频道收到的消息是你选的语言。

---

## 第 8 步：完整测试一遍

用一个**不在外交组**的小号：

1. 工单 → 提交工单 → 选「外交」→ 能看到「图片（选填）」上传框 → 紧急程度选 Urgent → 填标题和内容 → 提交。
   - ✅ Discord 外交频道收到新工单提醒，并 @ 了外交身份组。
   - ✅ 能看到上传框，说明图片文件夹配置正确。
2. 用外交人员的号打开这张工单 → 点「接手」→ 回复一句话。
   - ✅ 小号右上角铃铛收到通知。
   - ✅ 小号收到 Discord 私信。私信要同时满足这几条才会发：
     - 装了 aa-discordbot，并且做了第 5.2 步；
     - 小号在 AA 里绑定了 Discord，并且在你们的 Discord 服务器里；
     - 小号的「个人设置」里没关私信；
     - 「管理 → 设置」里的 Discord 私信开关是开着的。
3. 外交人员写一条「内部备注」。
   - ✅ 小号打开工单看不到这条备注。
4. 小号点「申请上级介入」（外交部门要先设了上级部门）。
   - ✅ 上级部门频道收到提醒。
5. 小号点「关闭工单」。
   - ✅ 工单状态变成「已关闭」，7 天内可以重新打开。

有任何一步不对，可以到 [GitHub Issues](https://github.com/yilifaer/aa-ticket/issues) 提问，附上现象和截图（**截图里不要带 webhook 地址**）。

---

## 出问题时怎么回滚

1. **先删掉插件的表**（以 `allianceserver` 身份，在项目目录里）：
   ```bash
   cd /home/allianceserver/myauth
   python manage.py migrate aa_ticket zero
   ```
   > 这一步要在恢复数据库之前做。否则恢复后插件的表还留着，以后再装会报 `table already exists`。
2. 删掉 Celery Beat 存在数据库里的 3 条定时任务（还是 `allianceserver`，在项目目录里）：
   ```bash
   python manage.py shell -c "from django_celery_beat.models import PeriodicTask; PeriodicTask.objects.filter(name__startswith='aa_ticket_').delete()"
   ```
   > 只从 `local.py` 删掉不够，数据库里还留着，Celery 会一直报找不到任务。如果下面要恢复装插件之前的数据库备份，这一步可以跳过。
3. 从 `local.py` 删掉安装时「第 3 步：修改 local.py」加的那段（或者把 `local.py.bak-aa-ticket-...` 复制回 `local.py`）。
4. 卸载插件：
   ```bash
   cd ~
   pip uninstall aa-ticket
   ```
5. 回到自己的账号（`exit`），需要的话恢复数据库：
   ```bash
   sudo mysql alliance_auth < ~/alliance_auth.bak-aa-ticket-时间.sql
   ```
6. 重启：
   ```bash
   sudo supervisorctl restart myauth:
   ```

**做完怎么确认：** AA 能正常打开，左侧菜单没有「工单」。

---

## 升级

升到新版本都这样做。把命令里的 `v1.0.1` 换成要装的版本号（版本列表见 [Releases](https://github.com/yilifaer/aa-ticket/releases)）。

```bash
sudo su allianceserver
cd ~
source /home/allianceserver/venv/auth/bin/activate
pip install -U "git+https://github.com/yilifaer/aa-ticket.git@v1.0.1"
cd /home/allianceserver/myauth
python manage.py migrate
python manage.py collectstatic --noinput
exit
sudo supervisorctl restart myauth:
```

升级前同样先做第 1 步的备份。

> 一定要用版本号（比如 `@v1.0.1`）安装，不要用分支名。用分支名安装的话，每次重装拿到的代码可能都不一样。
>
> 升级后**不要**用上面「出问题时怎么回滚」的办法退回旧版本，那会删掉所有工单。新版本有问题时，用同样的命令装回旧的版本号就行（数据库不用动，除非新版本的说明里写了有数据库变化）。
